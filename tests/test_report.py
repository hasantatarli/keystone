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


TECH_PANEL = 'class="panel panel-tech"'


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
            "subject_identifier, details) VALUES (%s, %s, %s, 'Long Idle Transaction', "
            "'Session 4711 idle <script>alert(1)</script>', 'Review the application.', "
            "1200, 'SECOND', 'SESSION', '4711', %s)",
            (run["assessment_run_id"], run["rule_id"], severity,
             '{"application": "billing-api", "user": "app_user", "client_addr": "10.0.5.21", '
             '"database": "orders", "last_query": "UPDATE invoices SET paid = true"}'))
        # The context above belongs to this check's time window.
        self.conn.execute(
            "UPDATE keystone.health_check SET started_at = now() - interval '5 minutes', "
            "finished_at = now() + interval '1 second' WHERE health_check_id = %s", (check_id,))
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
        self.assertIn("Dikkat gerektiren sorunlar var.", page)
        self.assertIn("Ölçülen: <b>20 dakika</b>", page)
        self.assertIn("Eşik: Uyarı ≥ 5 dakika · Kritik ≥ 15 dakika", page)
        self.assertIn("Son gözlenen sorgu", page)
        self.assertIn("Primary", page)
        self.assertIn("Replica", page)
        self.assertIn("3 gün", page)
        self.assertIn("orders", page)
        self.assertIn("5.0 GB", page)
        self.assertNotIn("template1", page)                       # templates hidden
        self.assertIn("connection refused", page)                 # why a source is missing
        self.assertIn("Bağlantı hatası", page)

    def test_two_parts_executive_first(self):
        page = self.render(self.make_check(), "tr")
        self.assertLess(page.index("panel panel-exec"), page.index(TECH_PANEL))
        executive = page[:page.index(TECH_PANEL)]
        # Plain-language Dictionary texts in the executive part, no technical context.
        self.assertIn("Uzun süre boşta bekleyen transaction", executive)
        self.assertIn("Olası sebep", executive)
        self.assertNotIn("billing-api", executive)
        self.assertNotIn("Session 4711", executive)

    def test_impact_categories_and_topics(self):
        page = self.render(self.make_check(), "tr")
        executive = page[:page.index(TECH_PANEL)]
        self.assertIn("Etkilenen alanlar", executive)
        self.assertIn("Performans", executive)                    # PG-TRAN-001 categories
        self.assertIn("Kapasite", executive)
        self.assertIn("Bu kontrolde incelenmedi", executive)      # Security has no rules yet
        self.assertIn("Transaction yönetimi", executive)
        self.assertIn("Değerlendirilemedi", executive)            # replication not assessed

    def test_technical_part_shows_who_and_where(self):
        page = self.render(self.make_check(), "tr")
        technical = page[page.index(TECH_PANEL):]
        self.assertIn("billing-api", technical)
        self.assertIn("app_user", technical)
        self.assertIn("10.0.5.21", technical)
        self.assertIn("UPDATE invoices SET paid = true", technical)
        self.assertIn("idle_in_transaction_session_timeout", technical)   # full recommendation

    def test_english_frame_and_texts(self):
        page = self.render(self.make_check(), "en")
        self.assertIn("Database Health Check Report", page)
        self.assertIn("Executive Summary", page)
        self.assertIn("Long idle transaction", page)
        self.assertNotIn("Yönetici", page)

    def test_database_text_is_escaped(self):
        page = self.render(self.make_check(), "tr")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_critical_finding_sets_the_verdict(self):
        page = self.render(self.make_check(critical=True), "en")
        self.assertIn("There are problems that need immediate action.", page)

    def test_report_without_context_data_still_renders(self):
        check_id = self.run_check()
        page = self.render(check_id, "tr")
        self.assertIn("Yönetici Özeti", page)
        self.assertIn("Bulgu yok.", page)

    def test_context_from_an_earlier_check_is_not_shown(self):
        old_check = self.make_check()
        new_check = self.run_check()          # nothing collected into the context tables
        self.assertNotEqual(old_check, new_check)
        page = self.render(new_check, "tr")
        self.assertNotIn("orders", page)
        self.assertNotIn("16.4", page)
        self.assertIn("Bu kontrolde toplanamadı.", page)

    def test_failed_collection_is_summarized_for_executives(self):
        self.failing = {"PG_REPLICATION_SLOTS"}
        page = self.render(self.run_check(), "tr")
        executive = page[:page.index(TECH_PANEL)]
        self.assertIn("Veri toplama: 6 / 8 başarılı", executive)   # + node-3 has no connection
        self.assertIn("connection refused", executive)

    def test_reasons_are_explained_in_plain_words(self):
        t = report.TEXTS["tr"]
        data = {"collections": [{"collector_key": "PG_ACTIVITY_SNAPSHOT",
                                 "status": "CONNECTION_FAILED",
                                 "status_message": "connection timeout expired"}]}
        self.assertEqual(
            report.explain_reason("PG_ACTIVITY_SNAPSHOT: Evidence is stale. Age=409325.3s, "
                                  "MaxAge=600s", data, t),
            "PG_ACTIVITY_SNAPSHOT bu kontrolde toplanamadı "
            "(Bağlantı hatası: connection timeout expired).")
        self.assertEqual(
            report.explain_reason("PG_TRANSACTION_WRAPAROUND: Evidence is stale. "
                                  "Age=409324.2s, MaxAge=86400s", data, t),
            "PG_TRANSACTION_WRAPAROUND verisi 4 gün 17 saat önce toplanmış; "
            "bu kontrol için en fazla 1 gün eski veri kabul ediliyor.")
        self.assertEqual(report.explain_reason("something else", data, t), "something else")

    def test_failed_collection_explains_the_rule_reason(self):
        self.failing = {"PG_REPLICATION_SLOTS"}
        page = self.render(self.run_check(), "tr")
        self.assertIn("PG_REPLICATION_SLOTS bu kontrolde toplanamadı", page)

    def test_default_file_name_has_target_and_check_time(self):
        check_id = self.make_check()
        data = report.load_report_data(self.conn, check_id)
        name = report.default_file_name(data, "tr")
        stamp = data["check"]["started_at"].strftime("%Y%m%d-%H%M")
        self.assertEqual(name, f"cluster_{stamp}_hc{check_id}_tr.html")

    def test_parts_are_css_tabs_and_both_print(self):
        page = self.render(self.make_check(), "tr")
        self.assertIn('id="tab-exec" checked', page)
        self.assertIn('<label for="tab-tech">Teknik Detaylar</label>', page)
        self.assertNotIn("<script", page)
        self.assertIn(".tabs>.panel{display:block!important", page)     # print shows both

    def test_executive_inventory_with_partial_host_data(self):
        check_id = self.make_check()
        now = self.conn.execute("SELECT now() AS n").fetchone()["n"]
        self.conn.execute(
            "INSERT INTO postgresql.host_snapshot (target_id, captured_at, source_type, "
            "logical_cpu_count, memory_total_bytes) VALUES (%s, %s, 'AUTOMATED', 4, %s)",
            (self.node1, now, 16 * 1024 ** 3))
        self.conn.execute(
            "INSERT INTO postgresql.storage_snapshot (target_id, captured_at, source_type, "
            "mount_point, used_bytes, total_bytes) VALUES (%s, %s, 'AUTOMATED', '/', %s, %s)",
            (self.node1, now, 30 * 1024 ** 3, 100 * 1024 ** 3))
        self.conn.commit()
        page = self.render(check_id, "tr")
        executive = page[:page.index(TECH_PANEL)]
        self.assertIn("Sistem envanteri", executive)
        self.assertIn("1 primary, 2 replica", executive)
        self.assertIn("4 çekirdek", executive)
        self.assertIn("16.0 GB", executive)
        self.assertIn("1 / 3 sunucu için", executive)      # host data only for one server
        self.assertIn("30.0 / 100.0 GB", executive)
        self.assertIn("%30 dolu", executive)
        self.assertIn("1 veritabanı", executive)

    def test_healthy_text_states_the_limit_used(self):
        check_id = self.make_check()
        # PG-TRAN-003 healthy, evaluated with a 30-minute warning threshold.
        self.conn.execute(
            "UPDATE keystone.assessment_result res SET outcome = 'HEALTHY', reason = NULL, "
            "thresholds_used = '[{\"severity\": \"WARNING\", \"value\": 1800, \"unit\": \"SECOND\"}, "
            "{\"severity\": \"CRITICAL\", \"value\": 3600, \"unit\": \"SECOND\"}]' "
            "FROM keystone.rule_definition rd WHERE rd.rule_id = res.rule_id "
            "AND rd.rule_key = 'PG-TRAN-003'")
        self.conn.commit()
        page = self.render(check_id, "tr")
        self.assertIn("Açık kalma süresi 30 dakika sınırını aşan transaction yok.", page)
        self.assertNotIn("{warning}", page)

    def test_thresholds_used_win_over_current_dictionary(self):
        check_id = self.make_check()
        self.conn.execute(
            "UPDATE keystone.assessment_result res SET thresholds_used = "
            "'[{\"severity\": \"WARNING\", \"value\": 120, \"unit\": \"SECOND\"}]' "
            "FROM keystone.rule_definition rd WHERE rd.rule_id = res.rule_id "
            "AND rd.rule_key = 'PG-TRAN-001'")
        self.conn.commit()
        page = self.render(check_id, "tr")
        self.assertIn("Eşik: Uyarı ≥ 2 dakika", page)
        self.assertNotIn("Uyarı ≥ 5 dakika", page)

    def test_quantities_are_readable(self):
        t = report.TEXTS["tr"]
        self.assertEqual(report.fmt_quantity(1_500_000_000, "TRANSACTION", t), "1.5 milyar transaction")
        self.assertEqual(report.fmt_quantity(1, "CONNECTION", t), "1 bağlantı")
        self.assertEqual(report.fmt_quantity(900, "SECOND", t), "15 dakika")

    def test_first_sentence(self):
        self.assertEqual(report.first_sentence("Bir. İki."), "Bir.")
        self.assertEqual(report.first_sentence("max_wal_size değeri 1.5 GB. Sonra"),
                         "max_wal_size değeri 1.5 GB.")
        self.assertEqual(report.first_sentence(""), "")

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
