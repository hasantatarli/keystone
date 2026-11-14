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
