"""Collector SQL against a real server: columns read through query_to_xml must not come back empty.

query_to_xml rows are read with xpath; a path relative to the row fragment that misses the row
element returns NULL silently (lab 2026-11-14: lock_wait_start was always empty). These tests run
the collectors themselves and look at the values.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_collector_sql.py -v
"""

import threading
import time
import unittest
from pathlib import Path

from psycopg.rows import dict_row

from test_installer_findings import DisposablePostgres

COLLECTORS = Path(__file__).resolve().parents[1] / "providers" / "postgresql" / "telemetry" / "collectors"


class CollectorSqlTests(unittest.TestCase):
    """Collectors whose values come through query_to_xml, run against PostgreSQL."""

    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)

    def connect(self):
        conn = self.server.connect(autocommit=True, row_factory=dict_row)
        self.addCleanup(conn.close)
        return conn

    def collect(self, name):
        return self.connect().execute((COLLECTORS / name).read_text(encoding="utf-8")).fetchall()

    def test_lock_wait_start_and_blocker(self):
        setup = self.connect()
        setup.execute("CREATE TABLE lock_test (id int PRIMARY KEY, v int); INSERT INTO lock_test VALUES (1, 0)")
        holder, waiter = self.connect(), self.connect()
        holder.execute("BEGIN; UPDATE lock_test SET v = 1 WHERE id = 1")
        waiter_pid = waiter.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        holder_pid = holder.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
        thread = threading.Thread(target=lambda: waiter.execute("UPDATE lock_test SET v = 2 WHERE id = 1"))
        thread.start()
        try:
            for _ in range(50):
                waiting = setup.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                                        (waiter_pid,)).fetchone()
                if waiting and waiting["wait_event_type"] == "Lock":
                    break
                time.sleep(0.1)
            rows = {r["pid"]: r for r in self.collect("activity_snapshot.sql")}
        finally:
            holder.execute("ROLLBACK")
            thread.join(10)
        self.assertEqual(rows[waiter_pid]["wait_event_type"], "Lock")
        self.assertEqual(rows[waiter_pid]["blocked_by"], [holder_pid])
        self.assertIsNotNone(rows[waiter_pid]["lock_wait_start"])       # PostgreSQL 14+
        self.assertIsNone(rows[holder_pid]["lock_wait_start"])


class HbaAndBloatCollectorTests(unittest.TestCase):
    """PG_HBA_RULES (PG026) and PG_TABLE_BLOAT (PG027) against a real server."""

    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)
        with cls.server.connect(autocommit=True) as conn:
            # 1 M rows of about 140 bytes (~160 MB), half deleted and vacuumed: about half is free space.
            conn.execute("CREATE TABLE bloated AS SELECT g AS id, repeat('x', 100) AS pad "
                         "FROM generate_series(1, 1000000) g")
            conn.execute("CREATE INDEX bloated_id ON bloated (id)")
            conn.execute("DELETE FROM bloated WHERE id % 2 = 0")
            conn.execute("VACUUM ANALYZE bloated")
            conn.execute("CREATE ROLE monitor LOGIN IN ROLE pg_monitor")

    def collect(self, name, role=None):
        with self.server.connect(autocommit=True, row_factory=dict_row) as conn:
            if role:
                conn.execute(f"SET ROLE {role}")
            return conn.execute((COLLECTORS / name).read_text(encoding="utf-8")).fetchall()

    def test_hba_rules_are_read_or_said_unreadable(self):
        rows = self.collect("hba_rules_snapshot.sql")
        rules = [r for r in rows if r["record_type"] == "RULE"]
        self.assertTrue(rows[0]["readable"])
        self.assertTrue(rules and all(r["conn_type"] and r["auth_method"] and r["line_number"] for r in rules))
        self.assertEqual([(r["record_type"], r["readable"]) for r in self.collect("hba_rules_snapshot.sql", "monitor")],
                         [("ACCESS", False)])

    def objects(self, rows):
        return {(r["object_kind"], r["object_name"]): r for r in rows if r["record_type"] == "OBJECT"}

    def test_bloat_from_statistics(self):
        rows = self.collect("table_bloat_snapshot.sql")
        self.assertFalse(rows[0]["pgstattuple_available"])
        table = self.objects(rows)[("TABLE", "bloated")]
        self.assertEqual(table["method"], "STATISTICS")
        self.assertAlmostEqual(table["wasted_bytes"] / table["size_bytes"], 0.5, delta=0.1)

    def test_without_select_on_the_table_nothing_is_guessed(self):
        table = self.objects(self.collect("table_bloat_snapshot.sql", "monitor"))[("TABLE", "bloated")]
        self.assertEqual((table["method"], table["wasted_bytes"]), (None, None))

    def test_bloat_with_pgstattuple_for_the_monitoring_role(self):
        with self.server.connect(autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS pgstattuple")
        try:
            rows = self.collect("table_bloat_snapshot.sql", "monitor")
            self.assertTrue(rows[0]["pgstattuple_available"])
            table = self.objects(rows)[("TABLE", "bloated")]
            self.assertEqual(table["method"], "PGSTATTUPLE")
            self.assertAlmostEqual(table["wasted_bytes"] / table["size_bytes"], 0.5, delta=0.1)
        finally:
            with self.server.connect(autocommit=True) as conn:
                conn.execute("DROP EXTENSION pgstattuple")


class QueryStatsCollectorTests(unittest.TestCase):
    """PG_QUERY_STATS (PG028): pg_stat_statements loaded, created and read; or said why not."""

    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start("shared_preload_libraries = 'pg_stat_statements'\n")
        cls.addClassCleanup(cls.server.close)

    def collect(self):
        with self.server.connect(autocommit=True, row_factory=dict_row) as conn:
            return conn.execute((COLLECTORS / "query_stats_snapshot.sql").read_text(encoding="utf-8")).fetchall()

    def test_loaded_but_not_created_then_read(self):
        system = self.collect()[0]
        self.assertEqual((system["record_type"], system["preloaded"], system["extension_created"],
                          system["available"]), ("SYSTEM", True, False, False))
        with self.server.connect(autocommit=True) as conn:
            conn.execute("CREATE EXTENSION pg_stat_statements")
            conn.execute("SET work_mem = '64kB'")
            for _ in range(3):
                conn.execute("SELECT count(*) FROM (SELECT g FROM generate_series(1, 200000) g ORDER BY g DESC) s")
        rows = self.collect()
        system, queries = rows[0], [r for r in rows if r["record_type"] == "QUERY"]
        self.assertTrue(system["available"])
        self.assertIsNotNone(system["stats_reset"])
        sort = next(q for q in queries if "generate_series" in (q["query_text"] or ""))
        self.assertEqual(sort["calls"], 3)
        self.assertGreater(sort["temp_blks_written"], 0)
        self.assertGreater(sort["total_ms"], 0)
        self.assertGreaterEqual(system["all_total_ms"], sort["total_ms"])
        self.assertLessEqual(len(queries), 20)


class QueryStatsNotLoadedTests(unittest.TestCase):

    def test_not_loaded(self):
        server = DisposablePostgres()
        server.start()
        self.addCleanup(server.close)
        with server.connect(autocommit=True, row_factory=dict_row) as conn:
            rows = conn.execute((COLLECTORS / "query_stats_snapshot.sql").read_text(encoding="utf-8")).fetchall()
        self.assertEqual([(r["record_type"], r["preloaded"], r["available"]) for r in rows],
                         [("SYSTEM", False, False)])
