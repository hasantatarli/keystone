"""Health check HTML report: content, language frame, escaping, file output.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_report.py -v
"""

from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path

from repository.report import health_check_report as report
import test_health_check


class ReportTests(test_health_check.HealthCheckTests):
    """Reuses the health check fixture (disposable repository, cluster with 3 nodes)."""

    def make_check(self, critical=False):
        self.failing = {"PG_REPLICATION_SLOTS"}
        check_id = self.run_check()
        now = datetime.now(timezone.utc)

        # Context evidence as the real collectors would have stored it.
        for node, recovery in ((self.node1, False), (self.node2, True), (self.node3, True)):
            self.conn.execute(
                "INSERT INTO postgresql.instance_inventory (target_id, server_version, "
                "server_address, server_port, in_recovery, postmaster_start_time) "
                "VALUES (%s, '16.4', %s, 5432, %s, %s)",
                (node, f"10.0.0.{node}", recovery, now - timedelta(days=3, hours=5)))
        self.conn.execute(
            "INSERT INTO postgresql.database_snapshot (target_id, captured_at, database_oid, "
            "database_name, database_owner, database_size_bytes, is_template) VALUES "
            "(%s, %s, 1, 'orders', 'app', 5368709120, FALSE), "
            "(%s, %s, 2, 'template1', 'postgres', 7000000, TRUE)",
            (self.system, now - timedelta(minutes=1), self.system, now - timedelta(minutes=1)))

        # One finding on PG-TRAN-001, as the engine would write it.
        run = self.conn.execute(
            "SELECT ar.assessment_run_id, rd.rule_id FROM keystone.assessment_run ar "
            "JOIN keystone.rule_definition rd ON rd.assessment_id = ar.assessment_id "
            "WHERE ar.health_check_id = %s AND rd.rule_key = 'PG-TRAN-001'", (check_id,)).fetchone()
        severity = "CRITICAL" if critical else "WARNING"
        self.conn.execute(
            "INSERT INTO keystone.finding (assessment_run_id, rule_id, severity, title, "
            "finding_text, recommendation, observed_value, observed_unit, subject_type, "
            "subject_identifier) VALUES (%s, %s, %s, 'Long Idle Transaction', "
            "'Session 4711 idle <script>alert(1)</script>', 'Review the application.', "
            "1200, 'SECOND', 'SESSION', '4711')", (run["assessment_run_id"], run["rule_id"], severity))
        self.conn.execute(
            "UPDATE keystone.assessment_result SET outcome = 'ATTENTION_REQUIRED', "
            "max_severity = %s, finding_count = 1, reason = NULL "
            "WHERE assessment_run_id = %s AND rule_id = %s",
            (severity, run["assessment_run_id"], run["rule_id"]))
        self.conn.commit()
        return check_id

    def render(self, check_id, lang):
        return report.render_html(report.load_report_data(self.conn, check_id), lang)

    def test_turkish_report_has_frame_findings_and_context(self):
        page = self.render(self.make_check(), "tr")

        self.assertIn('<html lang="tr">', page)
        self.assertIn("Veritabanı Sağlık Kontrolü Raporu", page)
        self.assertIn("Dikkat gerektiren bulgular var.", page)
        self.assertIn("Review the application.", page)            # Dictionary text stays English
        self.assertIn("1,200 SECOND", page)
        self.assertIn("Primary", page)
        self.assertIn("Replica", page)
        self.assertIn("3 gün", page)
        self.assertIn("orders", page)
        self.assertIn("5.0 GB", page)
        self.assertNotIn("template1", page)                       # templates hidden
        self.assertIn("connection refused", page)                 # why a source is missing
        self.assertIn("Bağlantı hatası", page)

    def test_english_frame(self):
        page = self.render(self.make_check(), "en")
        self.assertIn("Database Health Check Report", page)
        self.assertIn("Areas Not Assessed", page)
        self.assertNotIn("Bulgular", page)

    def test_database_text_is_escaped(self):
        page = self.render(self.make_check(), "tr")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_critical_finding_sets_the_verdict(self):
        page = self.render(self.make_check(critical=True), "en")
        self.assertIn("There are findings that need immediate action.", page)

    def test_report_without_context_data_still_renders(self):
        check_id = self.run_check()
        page = self.render(check_id, "tr")
        self.assertIn("Özet", page)
        self.assertIn("Bulgu yok.", page)

    def test_write_report_and_latest_check(self):
        check_id = self.make_check()
        self.assertEqual(report.latest_health_check_id(self.conn, self.system), check_id)
        with tempfile.TemporaryDirectory() as directory:
            path = report.write_report(self.conn, check_id, "en",
                                       output=Path(directory) / "r.html")
            self.assertTrue(path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>"))

    def test_unsupported_language_is_rejected(self):
        with self.assertRaises(ValueError):
            report.write_report(self.conn, self.make_check(), "de")

    def test_unknown_check(self):
        with self.assertRaises(ValueError):
            report.load_report_data(self.conn, 999999)

    def test_numeric_headers_align_with_values(self):
        html = report.table(["Name", "Size"], [["a", "1 GB"]], numeric=(1,))
        self.assertIn('<th class="num">Size</th>', html)
        self.assertIn('<td class="num">1 GB</td>', html)

    def test_format_helpers(self):
        self.assertEqual(report.fmt_bytes(1536), "1.5 KB")
        self.assertEqual(report.fmt_bytes(None), "")
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.assertEqual(report.fmt_uptime(start, start + timedelta(days=2, hours=3),
                                           report.TEXTS["en"]), "2 days 3 hours")


# The inherited health check tests already run in test_health_check.py.
for _name in [n for n in dir(test_health_check.HealthCheckTests) if n.startswith("test_")]:
    setattr(ReportTests, _name, None)


if __name__ == "__main__":
    unittest.main()
