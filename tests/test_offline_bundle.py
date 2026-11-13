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

    def test_p2_rules_on_real_evidence(self):
        # V056 end to end: real collectors, loaders, rules and both report languages.
        import threading
        with self.server.connect("app", autocommit=True) as app:
            app.execute("DROP TABLE IF EXISTS untouched")
            app.execute("CREATE TABLE untouched (id int) WITH (autovacuum_enabled = false)")
            app.execute("INSERT INTO untouched SELECT generate_series(1, 30000)")
        sleeper = self.server.connect("app", autocommit=True)
        worker = threading.Thread(target=lambda: sleeper.execute("SELECT pg_sleep(8)"), daemon=True)
        worker.start()
        self.addCleanup(sleeper.close)
        self.addCleanup(worker.join)
        import time
        time.sleep(3)
        with self.connect() as conn:                 # thresholds of the test, not the defaults
            conn.execute("UPDATE keystone.rule_threshold SET threshold_value = threshold_value / 300 "
                         "WHERE rule_id = (SELECT rule_id FROM keystone.rule_definition "
                         "WHERE rule_key = 'PG-TRAN-007')")
            conn.commit()
        try:
            files, host = self.evidence_files()
            check_id, _ = imp.import_bundle(self.connect, self.target, files, [host])
        finally:
            with self.connect() as conn:
                conn.execute("UPDATE keystone.rule_threshold SET threshold_value = threshold_value * 300 "
                             "WHERE rule_id = (SELECT rule_id FROM keystone.rule_definition "
                             "WHERE rule_key = 'PG-TRAN-007')")
                conn.commit()
        with self.connect() as conn:
            outcomes = {r["rule_key"]: (r["outcome"], r["max_severity"]) for r in conn.execute(
                "SELECT rd.rule_key, res.outcome, res.max_severity FROM keystone.assessment_result res "
                "JOIN keystone.assessment_run ar USING (assessment_run_id) "
                "JOIN keystone.rule_definition rd USING (rule_id) WHERE ar.health_check_id = %s",
                (check_id,))}
            subjects = {r["subject_identifier"] for r in conn.execute(
                "SELECT f.subject_identifier FROM keystone.finding f "
                "JOIN keystone.assessment_run ar USING (assessment_run_id) WHERE ar.health_check_id = %s",
                (check_id,))}
            pages = {lang: report.render_html(report.load_report_data(conn, check_id), lang)
                     for lang in ("tr", "en")}
        self.assertEqual(outcomes["PG-TRAN-007"], ("ATTENTION_REQUIRED", "WARNING"))
        self.assertEqual(outcomes["PG-MAINT-003"], ("ATTENTION_REQUIRED", "WARNING"))
        self.assertIn("app.public.untouched", subjects)
        self.assertEqual(outcomes["PG-TRAN-006"], ("HEALTHY", None))
        self.assertEqual(outcomes["PG-CAP-004"], ("HEALTHY", None))
        self.assertEqual(outcomes["PG-CONF-005"], ("ATTENTION_REQUIRED", "INFO"))
        self.assertEqual(outcomes["PG-HA-003"][0], "NOT_APPLICABLE")
        self.assertEqual(outcomes["PG-HA-004"][0], "NOT_APPLICABLE")
        self.assertIn(outcomes["PG-HA-002"][0], ("HEALTHY", "ATTENTION_REQUIRED"))
        self.assertIn("Uzun süren sorgu", pages["tr"])
        self.assertIn("Autovacuum analyze eşiği (satır)", pages["tr"])        # findings table columns
        self.assertIn("shared_preload_libraries", pages["tr"])
        self.assertIn("Long running query", pages["en"])

    def test_object_structure_rules_on_real_evidence(self):
        # V057 end to end: index definitions, foreign keys, unlogged tables and extensions.
        with self.server.connect("app", autocommit=True) as app:
            app.execute("""
                DROP TABLE IF EXISTS s_child, s_parent, s_cache;
                CREATE TABLE s_parent (id int PRIMARY KEY);
                CREATE TABLE s_child (id int PRIMARY KEY, parent_id int REFERENCES s_parent, a int, b int);
                INSERT INTO s_parent VALUES (1);
                INSERT INTO s_child SELECT g, 1, g, g FROM generate_series(1, 20000) g;
                CREATE INDEX s_child_a ON s_child (a);
                CREATE INDEX s_child_a_again ON s_child (a);
                CREATE INDEX s_child_a_b ON s_child (a, b);
                CREATE UNLOGGED TABLE s_cache (k text);
                DROP EXTENSION IF EXISTS pg_stat_statements;
                CREATE EXTENSION pg_stat_statements VERSION '1.9';
            """)
        parameter = ("UPDATE keystone.rule_parameter SET parameter_value = %s WHERE parameter_key = "
                     "'min_table_size' AND rule_id = (SELECT rule_id FROM keystone.rule_definition "
                     "WHERE rule_key = 'PG-IDX-004')")
        with self.connect() as conn:
            conn.execute(parameter, (8192,))
            conn.commit()
        try:
            files, host = self.evidence_files()
            check_id, _ = imp.import_bundle(self.connect, self.target, files, [host])
        finally:
            with self.connect() as conn:
                conn.execute(parameter, (10485760,))
                conn.commit()
            with self.server.connect("app", autocommit=True) as app:
                app.execute("DROP TABLE s_child, s_parent, s_cache; DROP EXTENSION pg_stat_statements")
        with self.connect() as conn:
            found = {(r["rule_key"], r["subject_identifier"], r["severity"]) for r in conn.execute(
                "SELECT rd.rule_key, f.subject_identifier, f.severity FROM keystone.finding f "
                "JOIN keystone.rule_definition rd USING (rule_id) "
                "JOIN keystone.assessment_run ar USING (assessment_run_id) WHERE ar.health_check_id = %s "
                "AND rd.rule_key IN ('PG-IDX-003', 'PG-IDX-004', 'PG-BKP-003', 'PG-LIFE-004')", (check_id,))}
            pages = {lang: report.render_html(report.load_report_data(conn, check_id), lang)
                     for lang in ("tr", "en")}
        self.assertEqual(found, {
            ("PG-IDX-003", "app.public.s_child_a_again", "WARNING"),
            ("PG-IDX-003", "app.public.s_child_a", "INFO"),
            ("PG-IDX-004", "app.public.s_child.s_child_parent_id_fkey", "WARNING"),
            ("PG-BKP-003", "app.public.s_cache", "WARNING"),
            ("PG-LIFE-004", "app.pg_stat_statements", "INFO")})
        self.assertIn("Sürüm ve yaşam döngüsü", pages["tr"])
        self.assertIn("Kapsanıyor", pages["tr"])
        self.assertIn("<code>btree (a, b)</code>", pages["tr"])
        self.assertIn("Foreign key without index", pages["en"])

    def test_a_database_without_tables_ends_with_its_latest_collection(self):
        # Lab hc110 (2026-11-10): after the test tables were dropped the database had no tables, the
        # collector returned nothing and the older snapshot with the dropped table was judged.
        from repository.intelligence import assessment_engine as engine
        sql = Path("providers/postgresql/telemetry/collectors/vacuum_analyze_snapshot.sql").read_text()
        with self.server.connect(autocommit=True) as admin:
            admin.execute("DROP DATABASE IF EXISTS vac_empty")
            admin.execute("CREATE DATABASE vac_empty")

        def drop():
            with self.server.connect(autocommit=True) as admin:
                admin.execute("DROP DATABASE IF EXISTS vac_empty")
        self.addCleanup(drop)

        def collect():
            with self.server.connect("vac_empty", row_factory=dict_row) as db:
                rows = db.execute(sql).fetchall()
            with self.connect() as conn:
                worker.save_vacuum_analyze_snapshot(
                    conn, {"target_id": self.target, "collector_key": "PG_VACUUM_ANALYZE"}, rows)
                conn.commit()
                return [r for r in engine.load_latest_vacuum_analyze_snapshot(conn, self.target)
                        if r["database_name"] == "vac_empty"]

        with self.server.connect("vac_empty", autocommit=True) as db:
            db.execute("CREATE TABLE gone (id int) WITH (autovacuum_enabled = false)")
            db.execute("INSERT INTO gone SELECT generate_series(1, 30000)")
        self.assertEqual({r["object_name"] for r in engine.table_rows(collect())}, {"gone"})
        with self.server.connect("vac_empty", autocommit=True) as db:
            db.execute("DROP TABLE gone")
        latest = collect()
        self.assertEqual([r["record_type"] for r in latest], ["DATABASE"])
        self.assertEqual(engine.table_rows(latest), [])

    def test_the_same_evidence_is_not_imported_twice(self):
        # Pilot 2026-11-11 (hc113): a second import clashed with its own rows and doubled others.
        files, host = self.evidence_files()
        check_id, _ = imp.import_bundle(self.connect, self.target, files, [host])
        with self.connect() as conn:
            before = conn.execute("SELECT count(*) AS n FROM keystone.health_check").fetchone()["n"]
        with self.assertRaisesRegex(imp.BundleError, rf"already imported as health check {check_id}"):
            imp.import_bundle(self.connect, self.target, files, [host])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM keystone.health_check").fetchone()["n"],
                             before)

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
        self.assertIn("generate the package again", row["status_message"])
        made = doc["generated_at"][:16].replace("T", " ")
        self.assertIn(f"the package of {made} UTC", row["status_message"])
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

    def test_linux_collector_walks_every_database_into_one_archive(self):
        # Answers to the prompts: server, port, user, password, SSH user (none), output folder.
        import subprocess
        out = self.dir / "collected"
        answers = f"127.0.0.1\n{self.server.port}\nkeystone_test\n\n\n{out}\n"
        result = subprocess.run(["sh", str(self.dir / "scripts" / "keystone_collect.sh")], input=answers,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = Path(f"{out}.tar.gz")
        self.assertTrue(archive.exists(), result.stdout)
        names = sorted(p.name for p in out.iterdir())
        self.assertIn("127.0.0.1_node.json", names)                       # named as the customer typed
        self.assertTrue({"127.0.0.1_db_app.json", "127.0.0.1_db_postgres.json"} <= set(names), names)
        with tempfile.TemporaryDirectory() as work:
            files, hosts = imp.expand([str(archive)], work)
            check_id, _ = imp.import_bundle(self.connect, self.target, files, hosts)
            with self.connect() as conn:
                statuses = {r["status"] for r in conn.execute(
                    "SELECT status FROM keystone.health_check_collection WHERE health_check_id = %s "
                    "AND collector_key <> 'PG_HOST_SNAPSHOT'", (check_id,))}
        self.assertEqual(statuses, {"SUCCESS"})

    def test_linux_collector_reads_other_servers_hosts_over_ssh(self):
        # Hasan 2026-11-10: one run collects everything; no copy, run, copy back per server.
        # The server is reached as 127.0.0.2 (not this machine) through a forwarder; ssh is a stand-in
        # that runs what it is sent, so the test shows the script goes on stdin and comes back whole.
        import os
        import socket
        import subprocess
        import threading

        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.2", self.server.port))
        listener.listen()

        def pipe(a, b):
            with contextlib.suppress(OSError):
                while data := a.recv(65536):
                    b.sendall(data)
            with contextlib.suppress(OSError):
                b.shutdown(socket.SHUT_WR)

        def forward():
            with contextlib.suppress(OSError):
                while True:
                    client, _ = listener.accept()
                    upstream = socket.create_connection(("127.0.0.1", self.server.port))
                    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
                    threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()

        threading.Thread(target=forward, daemon=True).start()
        bin_dir = self.dir / "bin"
        bin_dir.mkdir(exist_ok=True)
        stub = bin_dir / "ssh"
        stub.write_text(f'#!/bin/sh\necho "$@" > "{self.dir}/ssh_args"\nexec sh -s\n', encoding="utf-8")
        stub.chmod(0o755)
        self.addCleanup(listener.close)

        def collect(out):
            return subprocess.run(["sh", str(self.dir / "scripts" / "keystone_collect.sh")],
                                  input=f"127.0.0.2\n{self.server.port}\nkeystone_test\n\nadmin\n{out}\n",
                                  capture_output=True, text=True, timeout=120,
                                  env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"})

        out = self.dir / "collected_ssh"
        result = collect(out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("admin@127.0.0.2 sh -s", (self.dir / "ssh_args").read_text())
        host = (out / "127.0.0.2_host.txt").read_text(encoding="utf-8")
        self.assertTrue(host.startswith("===CAPTURED_AT==="), host[:200])
        self.assertIn("===FILESYSTEMS===", host)

        stub.write_text("#!/bin/sh\necho 'Permission denied' >&2\nexit 255\n", encoding="utf-8")
        out = self.dir / "collected_ssh_denied"
        result = collect(out)
        self.assertEqual(result.returncode, 0, result.stderr)                   # the SQL evidence still goes
        self.assertIn("SSH ile alinamadi", result.stderr)
        self.assertFalse((out / "127.0.0.2_host.txt").exists())
        self.assertTrue((out / "127.0.0.2_node.json").exists())

    def test_without_a_target_the_system_is_created_then_recognised(self):
        # The customer never knows Keystone's names: the import creates the system, then finds it again.
        def collect():                               # each import is a new collection
            files, host = self.evidence_files()
            renamed = []
            for f in files:
                to = Path(f).with_name(Path(f).name.replace("pg-off_", "dbsrv7_")
                                       .replace("dbsrv7_app", "dbsrv7_db_app")
                                       .replace("dbsrv7_postgres", "dbsrv7_db_postgres"))
                Path(f).replace(to)
                renamed.append(str(to))
            host_file = Path(host).with_name("dbsrv7_host.txt")
            Path(host).replace(host_file)
            return renamed, host_file

        renamed, host_file = collect()
        with self.connect() as conn:                 # this server's earlier imports are not the customer's
            conn.execute("UPDATE keystone.target SET is_active = FALSE WHERE target_id = %s", (self.target,))
            conn.commit()
        first, notes = imp.import_bundle(self.connect, None, renamed, [str(host_file)], name="Musteri DB",
                                         environment="PROD")
        self.assertEqual(notes[0], "created in Keystone: Musteri DB, dbsrv7")
        renamed, host_file = collect()
        second, notes = imp.import_bundle(self.connect, None, renamed, [str(host_file)])
        self.assertFalse(any(n.startswith("created") for n in notes))
        with self.connect() as conn:
            targets = {r["health_check_id"]: r["target_id"] for r in conn.execute(
                "SELECT health_check_id, target_id FROM keystone.health_check WHERE health_check_id = ANY(%s)",
                ([first, second],))}
            nodes = conn.execute("SELECT name, environment FROM keystone.target WHERE parent_target_id = %s",
                                 (targets[first],)).fetchall()
            conn.execute("UPDATE keystone.target SET is_active = FALSE WHERE target_id = %s "
                         "OR parent_target_id = %s", (targets[first], targets[first]))
            conn.commit()
        self.assertEqual(targets[first], targets[second])
        self.assertEqual([(n["name"], n["environment"]) for n in nodes], [("dbsrv7", "PROD")])

    def test_a_server_is_one_node_whether_typed_by_address_or_name(self):
        # Hasan 2026-11-10: first by IP, then by host name; the collector records what the name resolves to.
        with self.connect() as conn:
            conn.execute("UPDATE keystone.target SET is_active = FALSE WHERE target_id = %s", (self.target,))
            conn.commit()

        def bundle(label, resolved):
            folder = self.dir / f"bundle_{label}"
            folder.mkdir(exist_ok=True)
            out = []
            for f in self.evidence_files()[0]:                         # each import is a new collection
                kind = Path(f).stem.split("_", 1)[1]                    # node / app / postgres
                name = f"{label}_node.json" if kind == "node" else f"{label}_db_{kind}.json"
                text = imp.document_text(Path(f).read_text(encoding="utf-8"))
                (folder / name).write_text(text, encoding="utf-8")
                out.append(str(folder / name))
            (folder / f"{label}_server.json").write_text(json.dumps(
                {"typed": label, "label": label, "port": self.server.port, "resolved": resolved}), encoding="utf-8")
            return out

        first, notes = imp.import_bundle(self.connect, None, bundle("10.9.8.7", []))
        self.assertIn("10.9.8.7", notes[0])
        second, notes = imp.import_bundle(self.connect, None, bundle("dbhost", ["10.9.8.7"]))
        self.assertFalse(any(n.startswith("created") for n in notes), notes)
        third, notes = imp.import_bundle(self.connect, None, bundle("dbhost", []))   # the name is known now
        self.assertFalse(any(n.startswith("created") for n in notes), notes)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT c.target_id FROM keystone.health_check_collection c "
                "WHERE c.health_check_id = ANY(%s) AND c.collector_key = 'PG_CONFIGURATION_SNAPSHOT'",
                ([first, second, third],)).fetchall()
            system = conn.execute("SELECT parent_target_id FROM keystone.target WHERE target_id = %s",
                                  (rows[0]["target_id"],)).fetchone()["parent_target_id"]
            conn.execute("UPDATE keystone.target SET is_active = FALSE WHERE target_id = %s "
                         "OR parent_target_id = %s", (system, system))
            conn.commit()
        self.assertEqual(len(rows), 1)

    def test_one_archive_per_windows_server_imports_as_one_system(self):
        # Hasan 2026-11-10: a DBA on RDP runs the collector on each Windows server (localhost); the
        # archives go to one import and become one system, each server with its own host facts.
        import zipfile
        files, _ = self.evidence_files()
        with self.connect() as conn:
            conn.execute("UPDATE keystone.target SET is_active = FALSE WHERE target_id = %s", (self.target,))
            conn.commit()
        archives = []
        for label, replica in (("WINSRV-A", False), ("WINSRV-B", True)):
            archive = self.dir / f"keystone_evidence_{label}.zip"
            with zipfile.ZipFile(archive, "w") as z:
                for f in files:
                    doc = json.loads(imp.document_text(Path(f).read_text(encoding="utf-8")))
                    doc["server"]["in_recovery"] = replica
                    if doc["kind"] == "node":
                        name = f"{label}_node.json"
                    else:
                        name = f"{label}_db_{doc['server']['database']}.json"
                    z.writestr(name, json.dumps(doc))
                z.writestr(f"{label}_server.json", json.dumps(
                    {"typed": "localhost", "label": label, "port": self.server.port, "resolved": []}))
                z.writestr(f"{label}_host.txt", WINDOWS_HOST.replace("DBSRV01", label))
            archives.append(str(archive))
        with tempfile.TemporaryDirectory() as work:
            evidence, hosts = imp.expand(archives, work)
            check_id, notes = imp.import_bundle(self.connect, None, evidence, hosts)
        with self.connect() as conn:
            got = {(r["name"], r["collector_key"]): r["status"] for r in conn.execute(
                "SELECT t.name, c.collector_key, c.status FROM keystone.health_check_collection c "
                "JOIN keystone.target t USING (target_id) WHERE c.health_check_id = %s", (check_id,))}
            system = conn.execute("SELECT target_id FROM keystone.health_check WHERE health_check_id = %s",
                                  (check_id,)).fetchone()["target_id"]
            conn.execute("UPDATE keystone.target SET is_active = FALSE WHERE target_id = %s "
                         "OR parent_target_id = %s", (system, system))
            conn.commit()
        self.assertIn("created in Keystone", notes[0])
        for label in ("WINSRV-A", "WINSRV-B"):
            self.assertEqual(got[(label, "PG_HOST_SNAPSHOT")], "SUCCESS")
            self.assertEqual(got[(label, "PG_CONFIGURATION_SNAPSHOT")], "SUCCESS")
            self.assertEqual(got[(label, "PG_INDEX_USAGE")], "SUCCESS")

    def test_primary_only_collectors_are_skipped_on_a_replica(self):
        # Lab 2026-11-10: on Patroni replicas the node script failed (WAL control functions in recovery).
        node = (self.dir / "scripts" / "keystone_node.sql").read_text(encoding="utf-8")
        database = (self.dir / "scripts" / "keystone_database.sql").read_text(encoding="utf-8")
        guarded = "CASE WHEN pg_is_in_recovery() THEN NULL ELSE"
        self.assertEqual(node.count(guarded), 8)          # the SYSTEM collectors, not the 3 NODE ones
        self.assertEqual(database.count(guarded), 7)      # the DATABASE collectors, not PG_INDEX_USAGE
        # The guard is what PostgreSQL skips at run time: a failing subquery behind it does not run.
        with self.server.connect("postgres") as conn:
            skipped = conn.execute("SELECT CASE WHEN NOT pg_is_in_recovery() THEN NULL ELSE "
                                   "(SELECT 1 / (random() * 0)::int) END").fetchone()[0]
        self.assertIsNone(skipped)

    def test_windows_files_and_doubled_quotes_are_read(self):
        doc = '{"keystone_bundle": 1}'
        self.assertEqual(imp.decode(doc.encode("utf-16")).lstrip("\ufeff"), doc)   # PowerShell 5 '>'
        self.assertEqual(imp.document_text(doc.replace('"', '""')), doc)          # pgAdmin copy quoting

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
