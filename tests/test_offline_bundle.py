"""Offline evidence: generated scripts run on a real PostgreSQL, saved as a DBA would, imported.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_offline_bundle.py -v
"""

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from psycopg.rows import dict_row

from repository.install import install as installer
from repository.intelligence.assessment_engine import data_mount
from repository.offline import bundle
from repository.offline import import_bundle as imp
from repository.report import health_check_report as report
from repository.worker import worker
from test_installer_findings import DisposablePostgres

LINUX_HOST = """===CAPTURED_AT===
{captured}
===HOSTNAME===
pg-off
===OS_RELEASE===
PRETTY_NAME="Ubuntu 24.04.4 LTS"
VERSION_ID="24.04"
===UPTIME===
3600.5 100.0
===CPU===
4
===MEMORY===
MemTotal:        8000000 kB
MemAvailable:    4000000 kB
SwapTotal:       0 kB
SwapFree:        0 kB
===FILESYSTEMS===
Filesystem 1-blocks Used Available Capacity Mounted on
/dev/sda1 100000000000 30000000000 70000000000 30% /
===BLOCK_DEVICES===
/dev/sda1 0
===VIRTUALIZATION===
kvm
"""

# What host_snapshot_windows.ps1 prints (format checked here; the script itself runs on Windows).
WINDOWS_HOST = """===CAPTURED_AT===
2026-11-09T18:00:00Z
===OS_FAMILY===
WINDOWS
===HOSTNAME===
DBSRV01
===OS_RELEASE===
PRETTY_NAME="Microsoft Windows Server 2019 Standard"
VERSION_ID="10.0.17763"
===UPTIME===
86400
===CPU===
8
===MEMORY===
MemTotal: 16776676 kB
MemAvailable: 8000000 kB
SwapTotal: 2490368 kB
SwapFree: 2400000 kB
===FILESYSTEMS===
Filesystem 1-blocks Used Available Capacity Mounted on
C: 107374182400 53687091200 53687091200 50% C:\\
D: 536870912000 107374182400 429496729600 20% D:\\
===BLOCK_DEVICES===
C: 0
D: 1
===VIRTUALIZATION===
vmware
"""


class WindowsHostTests(unittest.TestCase):
    def test_windows_output_reads_like_linux(self):
        rows = worker.parse_host_snapshot_output(WINDOWS_HOST)
        host = rows[0]
        self.assertEqual((host["os_family"], host["logical_cpu_count"], host["virtualization"]),
                         ("WINDOWS", 8, "vmware"))
        storage = {r["mount_point"]: r for r in rows if r["record_type"] == "STORAGE"}
        self.assertEqual(set(storage), {"C:\\", "D:\\"})
        self.assertFalse(storage["C:\\"]["rotational"])
        # The data disk of a Windows data directory is found like a Linux one.
        self.assertEqual(data_mount("D:/PostgreSQL/16/data", list(storage.values()))["mount_point"], "D:\\")
        self.assertEqual(data_mount("C:\\Program Files\\PostgreSQL\\16\\data",
                                    list(storage.values()))["mount_point"], "C:\\")


class DocumentTextTests(unittest.TestCase):
    def test_pasted_pgadmin_file_and_psql_output(self):
        doc = '{"keystone_bundle": 1, "x": "a,b"}'
        self.assertEqual(imp.document_text(doc), doc)
        buffer = io.StringIO()
        csv.writer(buffer, quoting=csv.QUOTE_ALL).writerow(["keystone_evidence"])
        csv.writer(buffer, quoting=csv.QUOTE_ALL).writerow([doc])
        self.assertEqual(imp.document_text(buffer.getvalue()), doc)            # pgAdmin "save to file"
        self.assertEqual(imp.document_text("\ufeff" + doc + "\n"), doc)        # BOM, psql -At


class OfflineImportTests(unittest.TestCase):
    """A standalone server: node script once, database script in two databases, host output."""

    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)
        with cls.server.connect(autocommit=True) as admin:
            admin.execute("CREATE DATABASE keystone_repo")
            admin.execute("CREATE DATABASE app")
        with cls.server.connect("app", autocommit=True) as app:
            app.execute("CREATE TABLE orders (id bigserial PRIMARY KEY, note text)")
            app.execute("INSERT INTO orders (note) SELECT 'n' FROM generate_series(1, 100)")
        with patch.object(installer, "connect_repository", cls.connect), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.dir = Path(cls.temp.name)
        cls.scripts = bundle.write_bundle(cls.dir / "scripts")

    @classmethod
    def connect(cls):
        return cls.server.connect("keystone_repo", row_factory=dict_row)

    def setUp(self):
        with self.connect() as conn:
            self.target = conn.execute(
                "INSERT INTO keystone.target (name, provider, target_type, environment) "
                "VALUES ('pg-off', 'PostgreSQL', 'NODE', 'TEST') RETURNING target_id").fetchone()["target_id"]
            conn.commit()

    def tearDown(self):
        with self.connect() as conn:
            conn.execute("UPDATE keystone.target SET is_active = FALSE WHERE target_id = %s", (self.target,))
            conn.commit()

    def run_script(self, kind, database):
        sql = (self.dir / "scripts" / f"keystone_{kind}.sql").read_text(encoding="utf-8")
        with self.server.connect(database) as conn:
            return conn.execute(sql).fetchone()[0]

    def evidence_files(self, captured_host=None):
        """As a DBA would save them: pasted, saved by pgAdmin, written by psql."""
        node = self.dir / "pg-off_node.json"
        node.write_text(self.run_script("node", "postgres"), encoding="utf-8")
        app = self.dir / "pg-off_app.csv"
        with app.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(["keystone_evidence"])
            writer.writerow([self.run_script("database", "app")])
        postgres = self.dir / "pg-off_postgres.txt"
        postgres.write_text(self.run_script("database", "postgres") + "\n", encoding="utf-8")
        captured = json.loads(node.read_text())["server"]["captured_at"]
        host = self.dir / "host.txt"
        host.write_text(LINUX_HOST.format(captured=captured_host or captured), encoding="utf-8")
        return [str(node), str(app), str(postgres)], str(host)

    def test_import_builds_a_health_check_judged_at_capture_time(self):
        files, host = self.evidence_files()
        check_id, warnings = imp.import_bundle(self.connect, self.target, files, [host])
        self.assertEqual(warnings, [])
        with self.connect() as conn:
            check = conn.execute("SELECT * FROM keystone.health_check WHERE health_check_id = %s",
                                 (check_id,)).fetchone()
            self.assertEqual((check["status"], check["source"]), ("COMPLETED", "OFFLINE"))
            self.assertEqual({f["kind"] for f in check["bundle_info"]["files"]}, {"node", "database", "host"})
            collections = {r["collector_key"]: r["status"] for r in conn.execute(
                "SELECT collector_key, status FROM keystone.health_check_collection "
                "WHERE health_check_id = %s", (check_id,))}
            self.assertEqual(set(collections.values()), {"SUCCESS"}, collections)
            outcomes = {r["rule_key"]: r["outcome"] for r in conn.execute(
                "SELECT rd.rule_key, res.outcome FROM keystone.assessment_result res "
                "JOIN keystone.assessment_run ar USING (assessment_run_id) "
                "JOIN keystone.rule_definition rd USING (rule_id) WHERE ar.health_check_id = %s",
                (check_id,))}
            # Host evidence from the file: disk and memory rules are judged, not left out.
            self.assertEqual(outcomes["PG-CAP-001"], "HEALTHY")
            self.assertEqual(outcomes["PG-CONF-007"], "HEALTHY")
            self.assertNotIn("ERROR", outcomes.values())
            # Query texts never leave the customer.
            texts = conn.execute("SELECT count(*) AS n FROM postgresql.activity_snapshot "
                                 "WHERE target_id = %s AND query_text IS NOT NULL",
                                 (self.target,)).fetchone()["n"]
            self.assertEqual(texts, 0)
            # Both databases' tables arrived (the app table and its sequence).
            sequences = {r["sequence_name"] for r in conn.execute(
                "SELECT sequence_name FROM postgresql.sequence_capacity_snapshot WHERE target_id = %s",
                (self.target,))}
            self.assertIn("orders_id_seq", sequences)
            page = report.render_html(report.load_report_data(conn, check_id), "tr")
        self.assertIn("offline toplandı", page)
        self.assertIn("Ubuntu 24.04.4 LTS", page)

    def test_files_of_another_system_are_refused(self):
        files, _ = self.evidence_files()
        doc = json.loads(Path(files[0]).read_text())
        doc["server"]["system_identifier"] = "1"
        other = self.dir / "pg-off_other_node.json"
        other.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaisesRegex(imp.BundleError, "different PostgreSQL systems"):
            imp.import_bundle(self.connect, self.target, [files[1], str(other)])

    def test_a_changed_collector_is_not_imported_from_an_old_script(self):
        files, _ = self.evidence_files()
        doc = json.loads(Path(files[0]).read_text())
        doc["collectors"]["PG_ROLES"]["checksum"] = "0" * 64
        Path(files[0]).write_text(json.dumps(doc), encoding="utf-8")
        check_id, _ = imp.import_bundle(self.connect, self.target, files)
        with self.connect() as conn:
            row = conn.execute("SELECT status, status_message FROM keystone.health_check_collection "
                               "WHERE health_check_id = %s AND collector_key = 'PG_ROLES'",
                               (check_id,)).fetchone()
            host = conn.execute("SELECT status FROM keystone.health_check_collection "
                                "WHERE health_check_id = %s AND collector_key = 'PG_HOST_SNAPSHOT'",
                                (check_id,)).fetchone()
        self.assertEqual(row["status"], "FAILED")
        self.assertIn("generate the scripts again", row["status_message"])
        self.assertEqual(host["status"], "NOT_COLLECTED")                     # no host file given

    def test_cluster_files_go_to_their_servers_by_name(self):
        # A primary and a replica: files named after the servers; system-wide evidence from the primary.
        files, _ = self.evidence_files()
        with self.connect() as conn:
            system = conn.execute(
                "INSERT INTO keystone.target (name, provider, target_type, environment) "
                "VALUES ('pg-ha', 'PostgreSQL', 'SYSTEM', 'TEST') RETURNING target_id").fetchone()["target_id"]
            for name in ("ha-1", "ha-2"):
                conn.execute("INSERT INTO keystone.target (name, provider, target_type, environment, "
                             "parent_target_id) VALUES (%s, 'PostgreSQL', 'NODE', 'TEST', %s)", (name, system))
            conn.commit()
        primary = json.loads(Path(files[0]).read_text())
        replica = json.loads(Path(files[0]).read_text())
        replica["server"]["in_recovery"] = True
        named = []
        for name, doc in (("ha-1_node.json", primary), ("ha-2_node.json", replica)):
            (self.dir / name).write_text(json.dumps(doc), encoding="utf-8")
            named.append(str(self.dir / name))
        app = self.dir / "ha-1_app.json"
        app.write_text(imp.document_text(Path(files[1]).read_text(encoding="utf-8")), encoding="utf-8")
        check_id, _ = imp.import_bundle(self.connect, system, named + [str(app)])
        with self.connect() as conn:
            got = {(r["name"], r["collector_key"]): r["status"] for r in conn.execute(
                "SELECT t.name, c.collector_key, c.status FROM keystone.health_check_collection c "
                "JOIN keystone.target t USING (target_id) WHERE c.health_check_id = %s", (check_id,))}
        self.assertEqual(got[("ha-2", "PG_CONFIGURATION_SNAPSHOT")], "SUCCESS")
        self.assertEqual(got[("pg-ha", "PG_ROLES")], "SUCCESS")                 # from the primary
        self.assertEqual(got[("pg-ha", "PG_SEQUENCE_CAPACITY")], "SUCCESS")
        self.assertEqual(got[("ha-2", "PG_INDEX_USAGE")], "NOT_COLLECTED")      # no database file of ha-2

        with self.assertRaisesRegex(imp.BundleError, "cannot tell which server"):
            imp.import_bundle(self.connect, system, files)
        with self.connect() as conn:
            conn.execute("UPDATE keystone.target SET is_active = FALSE WHERE target_id = %s "
                         "OR parent_target_id = %s", (system, system))
            conn.commit()

    def test_offline_rows_are_stored_like_live_rows(self):
        # The same collector on the same server, live and through the JSON file: same stored values.
        collector = next(c for c in installer.discover_collectors()
                         if c["collector_key"] == "PG_CONFIGURATION_SNAPSHOT")
        with self.server.connect("postgres", row_factory=dict_row) as target:
            live_rows = target.execute(collector["path"].read_text(encoding="utf-8")).fetchall()
        files, _ = self.evidence_files()
        offline_rows = imp.collector_rows([imp.read_evidence(files[0])], "PG_CONFIGURATION_SNAPSHOT", {})
        with self.connect() as conn:
            live_target = conn.execute(
                "INSERT INTO keystone.target (name, provider, target_type, environment, is_active) "
                "VALUES ('live-copy', 'PostgreSQL', 'NODE', 'TEST', FALSE) RETURNING target_id"
            ).fetchone()["target_id"]
            worker.save_configuration_snapshot(conn, {"target_id": live_target}, live_rows)
            worker.save_configuration_snapshot(conn, {"target_id": self.target}, offline_rows)
            stored = {}
            for tid in (live_target, self.target):
                stored[tid] = {(r["setting_name"], r["setting_value"], r["unit"], r["source"])
                               for r in conn.execute(
                                   "SELECT setting_name, setting_value, unit, source "
                                   "FROM postgresql.configuration_snapshot WHERE target_id = %s "
                                   "AND setting_name NOT IN ('application_name')", (tid,))}
            conn.rollback()
        self.assertGreater(len(stored[live_target]), 300)
        self.assertEqual(stored[live_target], stored[self.target])

    def test_the_scripts_create_nothing_and_need_only_pg_monitor(self):
        with self.server.connect(autocommit=True) as admin:
            admin.execute("DROP ROLE IF EXISTS offline_monitor")
            admin.execute("CREATE ROLE offline_monitor LOGIN IN ROLE pg_monitor")
        import psycopg
        for kind in ("node", "database"):
            sql = (self.dir / "scripts" / f"keystone_{kind}.sql").read_text(encoding="utf-8")
            with psycopg.connect(host="127.0.0.1", port=self.server.port, user="offline_monitor",
                                 dbname="app") as conn:
                conn.read_only = True                                  # fails on any write
                self.assertTrue(json.loads(conn.execute(sql).fetchone()[0])["collectors"])


if __name__ == "__main__":
    unittest.main()
