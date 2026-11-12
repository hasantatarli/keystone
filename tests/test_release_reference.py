"""Release reference (V059): parsing the sources, storing, reference files, and stale references.

A version finding is only given on a reference that is current (Hasan 2026-11-11): these tests
pin that a stale reference makes PG-LIFE-001 INSUFFICIENT_EVIDENCE, never HEALTHY or a finding.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_release_reference.py -v
"""

import contextlib
from datetime import date, datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from psycopg import sql
from psycopg.rows import dict_row

from repository.install import install as installer
from repository.intelligence import assessment_engine as engine
from repository.lifecycle import release_reference as ref
from repository.report import health_check_report as report
from test_installer_findings import DisposablePostgres


# The table of https://www.postgresql.org/support/versioning/ as served on 2026-11-11 (rows shortened).
VERSIONING_PAGE = """
<table class="table table-striped">
  <thead><tr><th>Version</th><th>Current minor</th><th>Supported</th>
  <th>First Release</th><th>Final Release</th></tr></thead>
  <tbody>
  <tr><td>18</td><td>18.6</td><td>Yes</td><td>September 25, 2025</td><td>November 14, 2030</td></tr>
  <tr><td>17</td><td>17.11</td><td>Yes</td><td>September 26, 2024</td><td>November 8, 2029</td></tr>
  <tr><td>16</td><td>16.15</td><td>Yes</td><td>September 14, 2023</td><td>November 9, 2028</td></tr>
  <tr><td>15</td><td>15.19</td><td>Yes</td><td>October 13, 2022</td><td>November 11, 2027</td></tr>
  <tr><td>14</td><td>14.24</td><td>Yes</td><td>September 30, 2021</td><td>November 12, 2026</td></tr>
  <tr><td>13</td><td>13.23</td><td>No</td><td>September 24, 2020</td><td>November 13, 2025</td></tr>
  <tr><td>9.6</td><td>9.6.24</td><td>No</td><td>September 29, 2016</td><td>November 11, 2021</td></tr>
  </tbody>
</table>
"""

# endoflife.date API v1 (schema 1.2.1, as served for rhel on 2026-11-11), with PostgreSQL rows.
ENDOFLIFE = json.dumps({"schema_version": "1.2.1", "result": {"name": "postgresql", "releases": [
    {"name": name, "releaseDate": released, "eolFrom": eol, "isEol": False,
     "latest": {"name": latest, "date": "2026-11-11"}}
    for name, released, eol, latest in (
        ("18", "2025-09-25", "2030-11-14", "18.6"), ("17", "2024-09-26", "2029-11-08", "17.11"),
        ("16", "2023-09-14", "2028-11-09", "16.15"), ("15", "2022-10-13", "2027-11-11", "15.19"),
        ("14", "2021-09-30", "2026-11-12", "14.24"), ("9.6", "2016-09-29", "2021-11-11", "9.6.24"))]}})


class ParserTests(unittest.TestCase):

    def test_versioning_page(self):
        releases = ref.parse_versioning_page(VERSIONING_PAGE)
        self.assertEqual(len(releases), 7)
        self.assertEqual(releases[4], {"major_version": "14", "latest_minor": "14.24",
                                       "first_release": date(2021, 9, 30), "end_of_support": date(2026, 11, 12)})
        self.assertEqual(releases[-1]["latest_minor"], "9.6.24")

    def test_endoflife(self):
        releases = ref.parse_endoflife(ENDOFLIFE)
        self.assertEqual(releases[1]["end_of_support"], date(2029, 11, 8))
        self.assertEqual(releases[1]["latest_minor"], "17.11")

    def test_a_changed_page_is_refused_not_stored(self):
        with self.assertRaises(ref.ReferenceError):
            ref.parse_versioning_page("<html><body>maintenance</body></html>")
        wrong = json.loads(ENDOFLIFE)
        wrong["result"]["releases"][0]["latest"]["name"] = "17.3"     # a minor of another major
        with self.assertRaises(ref.ReferenceError):
            ref.parse_endoflife(json.dumps(wrong))

    def test_offline_refresh_says_why_and_does_not_raise(self):
        with patch.object(ref, "fetch", side_effect=OSError("no route to host")):
            ok, detail = ref.refresh(lambda: None)
        self.assertFalse(ok)
        self.assertIn("no route to host", detail)


class ReferenceStoreTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)
        cls.template = "reference_template_" + uuid.uuid4().hex
        with cls.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.template)))
        with patch.object(installer, "connect_repository", lambda: cls.server.connect(cls.template)), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()

    def setUp(self):
        self.database = "reference_test_" + uuid.uuid4().hex
        with self.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(self.database), sql.Identifier(self.template)))
        self.conn = self.connect()
        self.addCleanup(self.conn.close)

    def connect(self):
        return self.server.connect(self.database, row_factory=dict_row)

    def postgresql(self):
        sources, rows = ref.load(self.conn, "PostgreSQL")
        return sources[0], rows

    def test_seed_is_installed(self):
        source, rows = self.postgresql()
        self.assertEqual(source["source"], "SEED")
        self.assertIn(("14", "14.24", date(2026, 11, 12)),
                      [(r["major_version"], r["latest_minor"], r["end_of_support"]) for r in rows])
        sources, rows = ref.load(self.conn)
        self.assertEqual(sources[0]["product"], "PostgreSQL")
        self.assertIn(("Windows Server", "2016", date(2027, 1, 12)),
                      [(r["product"], r["major_version"], r["end_of_support"]) for r in rows])

    def test_online_refresh_stores_source_and_time(self):
        newer = VERSIONING_PAGE.replace("17.11", "17.12")
        with patch.object(ref, "fetch", return_value=newer):
            ok, url = ref.refresh(self.connect)
        self.assertTrue(ok)
        source, rows = self.postgresql()
        self.assertEqual((source["source"], source["source_detail"]), ("ONLINE", ref.VERSIONING_URL))
        self.assertLess(datetime.now(timezone.utc) - source["as_of"], timedelta(minutes=1))
        self.assertIn("17.12", [r["latest_minor"] for r in rows])

    def test_falls_back_to_endoflife(self):
        def fetch(url, timeout):
            if url == ref.VERSIONING_URL:
                raise OSError("blocked")
            return ENDOFLIFE
        with patch.object(ref, "fetch", side_effect=fetch):
            ok, url = ref.refresh(self.connect)
        self.assertEqual((ok, url), (True, ref.ENDOFLIFE_URL))

    def test_export_then_import_keeps_the_file_date(self):
        path = os.path.join(tempfile.mkdtemp(), "reference.json")
        ref.export(self.conn, path)
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(doc["products"][0]["product"], "PostgreSQL")
        doc["products"][0]["as_of"] = "2026-12-01T09:00:00+00:00"
        doc["products"][0]["releases"][0]["latest_minor"] = "18.7"
        Path(path).write_text(json.dumps(doc), encoding="utf-8")
        results = ref.import_file(self.conn, path)
        self.assertEqual(len(results), 10)                  # PostgreSQL and nine operating systems
        source, rows = self.postgresql()
        self.assertEqual((source["source"], source["as_of"]),
                         ("FILE", datetime(2026, 12, 1, 9, tzinfo=timezone.utc)))
        self.assertIn("18.7", [r["latest_minor"] for r in rows])

    def test_an_older_file_is_refused(self):
        path = os.path.join(tempfile.mkdtemp(), "reference.json")
        ref.export(self.conn, path)
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        doc["products"][0]["as_of"] = "2026-01-01T00:00:00+00:00"
        doc["products"][0]["releases"][0]["latest_minor"] = "18.0"
        Path(path).write_text(json.dumps(doc), encoding="utf-8")
        results = ref.import_file(self.conn, path)
        self.assertEqual(results[0][:2], ("PostgreSQL", False))
        self.assertEqual(self.postgresql()[0]["source"], "SEED")
        self.assertNotIn("18.0", [r["latest_minor"] for r in self.postgresql()[1]])

    def evaluate(self, rule_key, evaluation_time):
        rule = self.conn.execute(
            "SELECT rule_id, rule_key, default_severity, finding_template FROM keystone.rule_definition "
            "WHERE rule_key = %s", (rule_key,)).fetchone()
        inventory = [{"target_id": 1, "node_name": "pg1", "captured_at": evaluation_time,
                      "server_address": None, "in_recovery": False, "server_version": "14.20",
                      "server_version_num": 140020}]
        cache = {"PG_INSTANCE_INVENTORY": inventory}
        return engine.evaluate_rule(self.conn, rule, 1, evaluation_time, cache)

    def test_minor_rule_is_not_assessed_on_a_stale_reference(self):
        seed_as_of = self.postgresql()[0]["as_of"]
        outcome, findings, reason, _ = self.evaluate("PG-LIFE-001", seed_as_of + timedelta(days=101))
        self.assertEqual((outcome, findings), (engine.OUTCOME_INSUFFICIENT_EVIDENCE, []))
        self.assertTrue(reason.startswith("KEYSTONE_RELEASE_REFERENCE: Evidence is stale."))
        data = {"check": {"finished_at": seed_as_of + timedelta(days=101)}, "collections": []}
        text = report.explain_reason(reason, data, report.TEXTS["tr"])
        self.assertIn("sürüm referansı 101 gün önce alınmış", text)
        self.assertIn("--refresh", text)

    def test_minor_rule_on_a_current_reference(self):
        seed_as_of = self.postgresql()[0]["as_of"]
        outcome, findings, _, _ = self.evaluate("PG-LIFE-001", seed_as_of + timedelta(days=1))
        self.assertEqual(outcome, engine.OUTCOME_ATTENTION_REQUIRED)
        self.assertEqual((findings[0]["severity"], findings[0]["observed_value"]), ("CRITICAL", 4))

    def test_support_rule_accepts_an_old_reference(self):
        seed_as_of = self.postgresql()[0]["as_of"]
        outcome, findings, _, _ = self.evaluate("PG-LIFE-002", seed_as_of + timedelta(days=400))
        self.assertEqual(outcome, engine.OUTCOME_ATTENTION_REQUIRED)
        self.assertEqual(findings[0]["severity"], "CRITICAL")

    def test_health_checks_do_not_collect_the_reference(self):
        from repository.healthcheck import health_check
        keys = health_check.load_evidence_collectors(self.conn, ["PG_LIFECYCLE_HEALTH"])
        self.assertIn("PG_INSTANCE_INVENTORY", keys)
        self.assertNotIn("KEYSTONE_RELEASE_REFERENCE", keys)
        self.assertNotIn("KEYSTONE_OS_REFERENCE", keys)
        self.assertIn("PG_HOST_SNAPSHOT", keys)

    def test_os_rule_on_the_pilot_host(self):
        """The first pilot: Windows Server 2016, free security updates end 2027-01-12."""
        rule = self.conn.execute(
            "SELECT rule_id, rule_key, default_severity, finding_template FROM keystone.rule_definition "
            "WHERE rule_key = 'PG-LIFE-003'").fetchone()
        at = datetime(2026, 11, 11, 9, tzinfo=timezone.utc)
        hosts = [{"record_type": "HOST", "target_id": 1, "node_name": "db1", "captured_at": at,
                  "os_family": "WINDOWS", "os_name": "Microsoft Windows Server 2016 Standard",
                  "os_version": "10.0.14393", "memory_total_bytes": 1}]
        outcome, findings, _, _ = engine.evaluate_rule(self.conn, rule, 1, at, {"PG_HOST_SNAPSHOT": hosts})
        self.assertEqual(outcome, engine.OUTCOME_ATTENTION_REQUIRED)
        self.assertEqual((findings[0]["severity"], findings[0]["template_values"]["days_left"]), ("WARNING", 62))
        outcome, findings, _, _ = engine.evaluate_rule(
            self.conn, rule, 1, at, {"PG_HOST_SNAPSHOT": [dict(hosts[0], captured_at=datetime(2027, 1, 12, tzinfo=timezone.utc))]})
        self.assertEqual(findings[0]["severity"], "CRITICAL")


if __name__ == "__main__":
    unittest.main()
