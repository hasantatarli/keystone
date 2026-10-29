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
        # Every collection of this check succeeded except the replication slots.
        self.conn.execute(
            "UPDATE keystone.health_check_collection SET status = 'SUCCESS', status_message = NULL "
            "WHERE health_check_id = %s AND collector_key <> 'PG_REPLICATION_SLOTS'", (check_id,))
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
        # The new check cannot collect the context: older rows must not appear as current.
        self.failing = {"PG_DATABASE_INVENTORY", "PG_INSTANCE_INVENTORY"}
        new_check = self.run_check()
        self.assertNotEqual(old_check, new_check)
        page = self.render(new_check, "tr")
        self.assertNotIn("orders", page)
        self.assertNotIn("16.4", page)
        self.assertIn("Bu kontrolde toplanamadı.", page)

    def test_failed_collection_is_summarized_for_executives(self):
        self.failing = {"PG_REPLICATION_SLOTS"}
        page = self.render(self.run_check(), "tr")
        executive = page[:page.index(TECH_PANEL)]
        self.assertIn("Veri toplama: 19 / 26 başarılı", executive)  # + nodes without connections
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

    def add_host(self, node, cpu, memory_gb, mounts, data_directory=None, available_gb=None):
        now = self.conn.execute("SELECT now() AS n").fetchone()["n"]
        self.conn.execute(
            "INSERT INTO postgresql.host_snapshot (target_id, captured_at, source_type, "
            "logical_cpu_count, memory_total_bytes) VALUES (%s, %s, 'AUTOMATED', %s, %s)",
            (node, now, cpu, memory_gb * 1024 ** 3))
        for mount, used_gb, total_gb in mounts:
            self.conn.execute(
                "INSERT INTO postgresql.storage_snapshot (target_id, captured_at, source_type, "
                "mount_point, used_bytes, total_bytes, available_bytes) "
                "VALUES (%s, %s, 'AUTOMATED', %s, %s, %s, %s)",
                (node, now, mount, used_gb * 1024 ** 3, total_gb * 1024 ** 3,
                 None if available_gb is None else available_gb * 1024 ** 3))
        if data_directory:
            self.conn.execute(
                "INSERT INTO postgresql.configuration_snapshot (target_id, captured_at, "
                "setting_name, setting_value) VALUES (%s, %s, 'data_directory', %s)",
                (node, now, data_directory))

    def test_executive_inventory_per_server(self):
        check_id = self.make_check()
        self.add_host(self.node1, 4, 16, [("/", 30, 100), ("/var/lib/postgresql", 46, 50)],
                      "/var/lib/postgresql/16/main")
        self.add_host(self.node2, 2, 8, [("/", 41, 50)], "/var/lib/postgresql/16/main")
        self.conn.commit()
        page = self.render(check_id, "tr")
        executive = page[:page.index(TECH_PANEL)]

        self.assertIn("<th>Veri diski</th>", executive)            # a row per server
        self.assertIn("46.0 / 50.0 GB · %92", executive)           # data mount, not /
        self.assertIn("41.0 / 50.0 GB · %82", executive)           # data dir on /
        self.assertIn('class="m-crit"', executive)                 # colours from the rule limits
        self.assertIn('class="m-warn"', executive)
        self.assertIn("87.0 / 100.0 GB", executive)                # tile: data disks only
        self.assertIn("Bilinmiyor", executive)                     # node-3: no host data
        self.assertNotIn("Dikkat çeken noktalar", executive)       # judgements are rules
        technical = page[page.index(TECH_PANEL):]
        self.assertIn('/var/lib/postgresql <span class="note">(veri)</span>', technical)

    def test_data_disk_rule_end_to_end(self):
        from repository.intelligence import assessment_engine as engine
        self.add_host(self.node1, 4, 16, [("/", 30, 100), ("/var/lib/postgresql", 46, 50)],
                      "/var/lib/postgresql/16/main")
        self.add_host(self.node2, 4, 16, [("/", 20, 100)], "/var/lib/postgresql/16/main")
        self.conn.commit()
        engine.run_assessment(self.conn, "PG_CAPACITY_HEALTH", self.system)
        row = self.conn.execute(
            "SELECT res.outcome, res.max_severity, res.thresholds_used, f.subject_identifier, "
            "f.observed_value, f.finding_text FROM keystone.assessment_result res "
            "JOIN keystone.rule_definition rd USING (rule_id) "
            "LEFT JOIN keystone.finding f ON f.assessment_run_id = res.assessment_run_id "
            "WHERE rd.rule_key = 'PG-CAP-001' ORDER BY res.assessment_result_id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual((row["outcome"], row["max_severity"]), ("ATTENTION_REQUIRED", "CRITICAL"))
        self.assertEqual(row["subject_identifier"], "node-1")
        self.assertEqual(float(row["observed_value"]), 92.0)
        self.assertIn("/var/lib/postgresql on node-1 is 92% full", row["finding_text"])
        self.assertEqual({t["severity"] for t in row["thresholds_used"]}, {"WARNING", "CRITICAL"})

    def test_data_disk_rule_without_host_evidence_is_not_assessed(self):
        from repository.intelligence import assessment_engine as engine
        engine.run_assessment(self.conn, "PG_CAPACITY_HEALTH", self.system)
        row = self.conn.execute(
            "SELECT res.outcome, res.reason FROM keystone.assessment_result res "
            "JOIN keystone.rule_definition rd USING (rule_id) WHERE rd.rule_key = 'PG-CAP-001' "
            "ORDER BY res.assessment_result_id DESC LIMIT 1").fetchone()
        self.assertEqual(row["outcome"], "INSUFFICIENT_EVIDENCE")

    def test_disk_percent_matches_df(self):
        check_id = self.make_check()
        self.add_host(self.node1, 2, 4, [("/", 8.7, 11.2)], "/var/lib/postgresql/17/main",
                      available_gb=2.0)
        self.conn.commit()
        page = self.render(check_id, "tr")
        self.assertIn("8.7 / 11.2 GB · %81", page[:page.index(TECH_PANEL)])
        self.assertNotIn("%78", page)

    def test_tiles_count_checks_and_add_up(self):
        # Two findings of one rule: one check needs attention, not two.
        check_id = self.make_check()
        self.conn.execute(
            "INSERT INTO keystone.finding (assessment_run_id, rule_id, severity, title, finding_text, recommendation, "
            "observed_value, observed_unit, subject_type, subject_identifier) "
            "SELECT assessment_run_id, rule_id, 'WARNING', title, 'second', recommendation, 600, 'SECOND', 'SESSION', '4712' "
            "FROM keystone.finding LIMIT 1")
        self.conn.commit()
        data = report.load_report_data(self.conn, check_id)
        counts, verdict = report.summarize(data)
        self.assertEqual(counts["findings"], 2)
        self.assertEqual(counts["warning"], 1)
        self.assertEqual(counts["critical"] + counts["warning"] + counts["healthy"]
                         + counts["not_assessed"], counts["total"])
        executive = report.render_html(data, "tr")
        executive = executive[:executive.index(TECH_PANEL)]
        self.assertNotIn('<div class="l">Bulgu</div>', executive)
        self.assertIn("2 bulgu", executive)                         # on the problem card

    def test_affected_areas_name_the_problem(self):
        page = self.render(self.make_check(), "tr")
        executive = page[:page.index(TECH_PANEL)]
        impact = executive[executive.index("Etkilenen alanlar"):executive.index("Alanlara göre durum")]
        # PG-TRAN-001 affects Performance and Capacity: the same name in both rows.
        self.assertEqual(impact.count("Uzun süre boşta bekleyen transaction"), 2)
        self.assertNotIn("1 bulgu", impact)
        self.assertIn("Aynı sorun birden fazla alanı etkileyebilir", impact)

    def test_os_is_shown_and_postgres_build_string_only_on_hover(self):
        check_id = self.make_check()
        self.add_host(self.node1, 2, 4, [("/", 5, 10)])
        self.conn.execute("UPDATE postgresql.host_snapshot SET os_name = 'Ubuntu 24.04.4 LTS', "
                          "os_version = '24.04' WHERE target_id = %s", (self.node1,))
        self.conn.execute("UPDATE postgresql.instance_inventory SET server_version = "
                          "'17.10 (Ubuntu 17.10-1.pgdg24.04+1)'")
        self.conn.commit()
        page = self.render(check_id, "tr")
        executive = page[:page.index(TECH_PANEL)]
        self.assertIn("<th>İşletim sistemi</th>", executive)
        self.assertIn("Ubuntu 24.04.4 LTS", executive)
        technical = page[page.index(TECH_PANEL):]
        self.assertIn('<span title="17.10 (Ubuntu 17.10-1.pgdg24.04+1)">17.10</span>', technical)
        self.assertNotIn(">17.10 (Ubuntu", page)                     # never as visible text

    def test_replication_status_collector_stores_sync_names_and_feeds_the_rules(self):
        from psycopg.rows import dict_row
        from repository.intelligence import assessment_engine as engine
        from repository.worker import worker
        sql = Path("providers/postgresql/telemetry/collectors/replication_status_snapshot.sql").read_text()
        with self.conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(sql).fetchall()
        worker.save_replication_status_snapshot(self.conn, {"target_id": self.system}, rows)
        self.conn.execute("UPDATE postgresql.replication_status_snapshot "
                          "SET synchronous_standby_names = 'ANY 1 (*)' WHERE target_id = %s",
                          (self.system,))
        now = self.conn.execute("SELECT now() AS n").fetchone()["n"]
        for node, address, recovery in ((self.node1, "10.0.0.1", False), (self.node2, "10.0.0.2", True)):
            self.conn.execute(
                "INSERT INTO postgresql.instance_inventory (target_id, server_address, in_recovery, "
                "last_collected_at) VALUES (%s, %s, %s, %s) ON CONFLICT (target_id) DO UPDATE "
                "SET server_address = EXCLUDED.server_address, in_recovery = EXCLUDED.in_recovery, "
                "last_collected_at = EXCLUDED.last_collected_at", (node, address, recovery, now))
        self.conn.commit()
        engine.run_assessment(self.conn, "PG_REPLICATION_HEALTH", self.system)
        outcomes = {r["rule_key"]: (r["outcome"], r["max_severity"]) for r in self.conn.execute(
            "SELECT rd.rule_key, res.outcome, res.max_severity FROM keystone.assessment_result res "
            "JOIN keystone.rule_definition rd USING (rule_id) "
            "WHERE res.assessment_run_id = (SELECT max(assessment_run_id) FROM keystone.assessment_run)"
        ).fetchall()}
        self.assertEqual(outcomes["PG-REP-003"], ("HEALTHY", None))
        self.assertEqual(outcomes["PG-REP-004"], ("ATTENTION_REQUIRED", "CRITICAL"))   # node-2 missing
        self.assertEqual(outcomes["PG-REP-006"], ("ATTENTION_REQUIRED", "CRITICAL"))

    def test_problem_cards_list_causes_and_steps(self):
        page = self.render(self.make_check(), "tr")
        executive = page[:page.index(TECH_PANEL)]
        card = executive[executive.index("Öne çıkan sorunlar"):executive.index("Sistem envanteri")
                         if "Sistem envanteri" in executive else None]
        # Closed by default: name, severity and what is happening in one line; the rest on demand.
        self.assertIn('<details class="card WARNING"><summary><h3>', card)
        self.assertIn('<div class="lead">Bazı session', card)
        self.assertNotIn("<dt>Ne oluyor</dt>", card)
        self.assertIn("<dt>Olası sebepler</dt><dd><ul class=\"items\"><li>", card)
        self.assertIn("<li>Connection pool session&#x27;ı bırakmıyor</li>", card)
        self.assertIn("<dt>Ne yapılmalı</dt><dd><ul class=\"items\">", card)
        technical = page[page.index(TECH_PANEL):]
        self.assertIn("<dt>Olası sebepler</dt>", technical)
        self.assertIn("idle_in_transaction_session_timeout", technical)
        self.assertIn('<details class="card WARNING"><summary><h3>', technical)
        self.assertIn('<details class="section"><summary><h2>Toplanan Veriler', technical)

    def test_list_items(self):
        self.assertEqual(report.list_items("- a\n- b"), ["a", "b"])
        self.assertIsNone(report.list_items("Plain text. Two sentences."))
        self.assertIn("<li>a</li>", report.render_text("- a\n- b"))
        self.assertEqual(report.render_text("One. Two.", short=True), "One.")

    def test_configuration_rules_on_real_settings(self):
        from psycopg.rows import dict_row
        from repository.intelligence import assessment_engine as engine
        from repository.worker import worker
        sql = Path("providers/postgresql/telemetry/collectors/configuration_snapshot.sql").read_text()
        for node in (self.node1, self.node2):
            with self.conn.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(sql).fetchall()
            worker.save_configuration_snapshot(self.conn, {"target_id": node}, rows)
        # Defaults are safe; one node with synchronous_commit off is a conscious-choice WARNING.
        self.conn.execute("UPDATE postgresql.configuration_snapshot SET setting_value = 'off' "
                          "WHERE target_id = %s AND setting_name = 'synchronous_commit'", (self.node2,))
        self.conn.commit()
        engine.run_assessment(self.conn, "PG_CONFIGURATION_HEALTH", self.system)
        outcomes = {r["rule_key"]: (r["outcome"], r["max_severity"]) for r in self.conn.execute(
            "SELECT rd.rule_key, res.outcome, res.max_severity FROM keystone.assessment_result res "
            "JOIN keystone.rule_definition rd USING (rule_id) "
            "WHERE res.assessment_run_id = (SELECT max(assessment_run_id) FROM keystone.assessment_run)"
        ).fetchall()}
        self.assertEqual(outcomes, {"PG-CONF-001": ("HEALTHY", None),
                                    "PG-CONF-002": ("ATTENTION_REQUIRED", "WARNING"),
                                    "PG-CONF-004": ("HEALTHY", None)})
        text = self.conn.execute("SELECT finding_text FROM keystone.finding ORDER BY finding_id DESC "
                                 "LIMIT 1").fetchone()["finding_text"]
        self.assertEqual(text, "Setting synchronous_commit is off on node-2.")

    def test_context_tolerates_target_clocks_slightly_behind(self):
        # Lab 2026-10-21: VM clocks behind the laptop; this check's inventory looked "not collected".
        check_id = self.make_check()
        self.conn.execute("UPDATE postgresql.instance_inventory SET last_collected_at = "
                          "(SELECT started_at FROM keystone.health_check WHERE health_check_id = %s) "
                          "- interval '30 seconds'", (check_id,))
        self.conn.commit()
        page = self.render(check_id, "tr")
        self.assertIn("1 primary, 2 replica", page)

    def test_context_of_a_node_this_check_could_not_reach_is_hidden(self):
        # Lab 2026-10-21: postgre-1 unreachable; its last inventory must not look current.
        check_id = self.make_check()
        self.conn.execute(
            "UPDATE keystone.health_check_collection SET status = 'CONNECTION_FAILED' "
            "WHERE health_check_id = %s AND target_id = %s AND collector_key = 'PG_INSTANCE_INVENTORY'",
            (check_id, self.node2))
        self.conn.commit()
        page = self.render(check_id, "tr")
        self.assertIn("1 primary, 1 replica", page)
        self.assertNotIn("10.0.0.%s" % self.node2, page)

    def test_attention_topic_explains_the_problem_and_what_was_fine(self):
        check_id = self.make_check()
        self.conn.execute(
            "UPDATE keystone.assessment_result res SET outcome = 'HEALTHY', reason = NULL "
            "FROM keystone.rule_definition rd WHERE rd.rule_id = res.rule_id "
            "AND rd.rule_key = 'PG-TRAN-003'")
        self.conn.commit()
        page = self.render(check_id, "tr")
        executive = page[:page.index(TECH_PANEL)]
        topics = executive[executive.index("Alanlara göre durum"):]
        # One item per rule: the problem with its severity first, then what was fine.
        # One bullet per rule; severity in the bullet colour and in words, all texts aligned.
        self.assertIn('<li class="r-warning"><b>Uzun süre boşta bekleyen transaction</b> '
                      '(1 bulgu, uyarı): Bazı session', topics)
        self.assertIn('<li class="r-ok">Açık kalma süresi', topics)   # the healthy rule of the topic
        results = page[page.index("Kontrol sonuçları"):]
        self.assertIn("1 bulgu · Eşik: Uyarı ≥ 5 dakika", results)

    def test_topic_lists_a_rule_that_could_not_be_assessed(self):
        # A topic must not read "no problems" while one of its rules was not assessed.
        check_id = self.make_check()
        self.conn.execute(
            "UPDATE keystone.assessment_result res SET outcome = 'HEALTHY', max_severity = NULL, "
            "finding_count = 0, reason = NULL FROM keystone.rule_definition rd "
            "WHERE rd.rule_id = res.rule_id AND rd.rule_key IN ('PG-TRAN-001', 'PG-TRAN-003', 'PG-TRAN-005')")
        self.conn.execute("DELETE FROM keystone.finding")
        self.conn.execute(
            "UPDATE keystone.assessment_result res SET outcome = 'INSUFFICIENT_EVIDENCE', "
            "reason = 'PG_PREPARED_TRANSACTIONS: Required evidence is not available.' "
            "FROM keystone.rule_definition rd WHERE rd.rule_id = res.rule_id AND rd.rule_key = 'PG-TRAN-005'")
        self.conn.commit()
        page = self.render(check_id, "tr")
        topics = page[page.index("Alanlara göre durum"):page.index(TECH_PANEL)]
        transactions = topics[topics.index("Transaction yönetimi"):]
        transactions = transactions[:transactions.index('<div class="topic">')]
        self.assertIn('<li class="r-unknown"><b>Uzun bekleyen prepared transaction</b> '
                      '(değerlendirilemedi): PG_PREPARED_TRANSACTIONS verisi yok.</li>', transactions)

    def test_many_findings_show_ten_and_the_rest_on_demand(self):
        check_id = self.make_check()
        run = self.conn.execute(
            "SELECT assessment_run_id, rule_id FROM keystone.finding LIMIT 1").fetchone()
        for i in range(14):
            self.conn.execute(
                "INSERT INTO keystone.finding (assessment_run_id, rule_id, severity, title, finding_text, "
                "recommendation, observed_value, observed_unit, subject_type, subject_identifier) "
                "VALUES (%s, %s, 'WARNING', 't', %s, 'r', %s, 'SECOND', 'SESSION', %s)",
                (run["assessment_run_id"], run["rule_id"], f"extra finding {i:02d}", 400 + i, str(i)))
        self.conn.commit()
        page = self.render(check_id, "tr")
        technical = page[page.index(TECH_PANEL):]
        self.assertIn('<details class="more"><summary>Tümünü göster (15)</summary>', technical)
        shown = technical[:technical.index('<details class="more">')]
        self.assertEqual(shown.count('class="instance"'), 10)
        self.assertIn("extra finding 13", shown)          # largest values first
        self.assertNotIn("extra finding 00", shown)

    def test_maintenance_rules_end_to_end_with_parameters(self):
        from repository.intelligence import assessment_engine as engine
        now = self.conn.execute("SELECT now() AS n").fetchone()["n"]
        rows = [  # (captured_at offset, database, table, live, dead, modified)
            (-600, "app", "old_orders", 1000, 900000, 0),     # older snapshot of app: ignored
            (0, "app", "orders", 60000, 40000, 0),           # 40 % dead -> CRITICAL
            (0, "app", "events", 1000000000, 60000000, 0),   # large table -> WARNING
            (0, "crm", "contacts", 100000, 0, 30000),        # 30 % changed -> WARNING (stale)
        ]
        for i, (offset, db, table, live, dead, modified) in enumerate(rows):
            self.conn.execute(
                "INSERT INTO postgresql.vacuum_analyze_snapshot (target_id, captured_at, database_oid, "
                "database_name, schema_name, object_oid, object_name, is_partition, n_live_tup, "
                "n_dead_tup, n_mod_since_analyze) VALUES (%s, %s + make_interval(secs => %s), 1, %s, "
                "'public', %s, %s, FALSE, %s, %s, %s)",
                (self.system, now, offset, db, 100 + i, table, live, dead, modified))
        self.conn.commit()
        engine.run_assessment(self.conn, "PG_MAINTENANCE_HEALTH", self.system)
        findings = {r["subject_identifier"]: r["severity"] for r in self.conn.execute(
            "SELECT f.subject_identifier, f.severity FROM keystone.finding f "
            "WHERE f.assessment_run_id = (SELECT max(assessment_run_id) FROM keystone.assessment_run)"
        ).fetchall()}
        self.assertEqual(findings, {"app.public.orders": "CRITICAL", "app.public.events": "WARNING",
                                    "crm.public.contacts": "WARNING"})
        used = self.conn.execute(
            "SELECT res.parameters_used FROM keystone.assessment_result res "
            "JOIN keystone.rule_definition rd USING (rule_id) WHERE rd.rule_key = 'PG-MAINT-001' "
            "ORDER BY res.assessment_result_id DESC LIMIT 1").fetchone()["parameters_used"]
        self.assertEqual(used["large_table_dead_tuples"], {"value": 50000000.0, "unit": "ROW"})

    def latest_outcomes(self):
        return {r["rule_key"]: (r["outcome"], r["max_severity"], r["reason"]) for r in self.conn.execute(
            "SELECT rd.rule_key, res.outcome, res.max_severity, res.reason "
            "FROM keystone.assessment_result res JOIN keystone.rule_definition rd USING (rule_id) "
            "WHERE res.assessment_run_id = (SELECT max(assessment_run_id) FROM keystone.assessment_run)"
        ).fetchall()}

    def test_wal_status_and_prepared_transaction_collectors_feed_the_rules(self):
        from psycopg.rows import dict_row
        from repository.intelligence import assessment_engine as engine
        from repository.worker import worker
        wal_sql = Path("providers/postgresql/telemetry/collectors/wal_status_snapshot.sql").read_text()
        prepared_sql = Path("providers/postgresql/telemetry/collectors/"
                            "prepared_transactions_snapshot.sql").read_text()
        with self.conn.cursor(row_factory=dict_row) as cur:
            wal_rows = cur.execute(wal_sql).fetchall()
            prepared_rows = cur.execute(prepared_sql).fetchall()
        self.assertEqual(len(wal_rows), 1)
        self.assertEqual((wal_rows[0]["in_recovery"], wal_rows[0]["timeline_id"]), (False, 1))
        self.assertEqual([r["record_type"] for r in prepared_rows], ["SYSTEM"])
        worker.save_wal_status_snapshot(self.conn, {"target_id": self.node1}, wal_rows)
        worker.save_prepared_transactions_snapshot(self.conn, {"target_id": self.system}, prepared_rows)
        self.conn.commit()

        engine.run_assessment(self.conn, "PG_BACKUP_HEALTH", self.system)
        self.assertEqual(self.latest_outcomes()["PG-BKP-001"][:2], ("HEALTHY", None))
        engine.run_assessment(self.conn, "PG_TRANSACTION_HEALTH", self.system)
        self.assertEqual(self.latest_outcomes()["PG-TRAN-005"][:2], ("HEALTHY", None))
        engine.run_assessment(self.conn, "PG_REPLICATION_HEALTH", self.system)
        self.assertEqual(self.latest_outcomes()["PG-HA-001"][:2], ("HEALTHY", None))    # timeline 1

        # A failover 3 hours ago and a prepared transaction waiting for 2 hours.
        self.conn.execute("UPDATE postgresql.wal_status_snapshot SET timeline_id = 126, "
                          "timeline_history_file = '0000007E.history', "
                          "timeline_started_at = captured_at - interval '3 hours'")
        self.conn.execute(
            "INSERT INTO postgresql.prepared_transaction_snapshot (target_id, captured_at, "
            "transaction_id, gid, prepared_at, owner, database_name) "
            "SELECT target_id, captured_at, '4242'::xid, 'tm-orders-17', captured_at - interval '2 hours', "
            "'app', 'orders' FROM postgresql.prepared_transaction_status_snapshot")
        self.conn.commit()
        engine.run_assessment(self.conn, "PG_REPLICATION_HEALTH", self.system)
        self.assertEqual(self.latest_outcomes()["PG-HA-001"][:2], ("ATTENTION_REQUIRED", "WARNING"))
        engine.run_assessment(self.conn, "PG_TRANSACTION_HEALTH", self.system)
        self.assertEqual(self.latest_outcomes()["PG-TRAN-005"][:2], ("ATTENTION_REQUIRED", "CRITICAL"))
        finding = self.conn.execute("SELECT finding_text, template_values FROM keystone.finding "
                                    "ORDER BY finding_id DESC LIMIT 1").fetchone()
        self.assertEqual(finding["template_values"]["gid"], "tm-orders-17")

        # Without the history file the failover time is unknown: not assessed, never healthy.
        self.conn.execute("UPDATE postgresql.wal_status_snapshot SET timeline_history_file = NULL, "
                          "timeline_started_at = NULL")
        self.conn.commit()
        engine.run_assessment(self.conn, "PG_REPLICATION_HEALTH", self.system)
        outcome, _, reason = self.latest_outcomes()["PG-HA-001"]
        self.assertEqual(outcome, "INSUFFICIENT_EVIDENCE")
        self.assertIn("[no_timeline_history]", reason)
        t = report.TEXTS["tr"]
        self.assertEqual(report.explain_reason(reason, {"collections": []}, t),
                         t["reason_codes"]["no_timeline_history"])

    def test_index_schema_and_role_collectors_feed_the_rules(self):
        from psycopg.rows import dict_row
        from repository.intelligence import assessment_engine as engine
        from repository.worker import worker
        collectors = Path("providers/postgresql/telemetry/collectors")
        self.conn.commit()
        self.conn.autocommit = True
        for statement in (
                "CREATE TABLE idx_test (id int, code text)",
                "INSERT INTO idx_test SELECT g, 'c' || (g % 10) FROM generate_series(1, 2000) g",
                "CREATE INDEX idx_test_unused ON idx_test (code)",
                "CREATE TABLE idx_test_ext (id int)",
                "CREATE INDEX idx_test_ext_id ON idx_test_ext (id)",
                "ALTER EXTENSION plpgsql ADD TABLE idx_test_ext",     # an extension's own table
                "GRANT CREATE ON SCHEMA public TO PUBLIC",
                "CREATE ROLE idx_test_admin LOGIN SUPERUSER"):
            self.conn.execute(statement)
        with self.assertRaises(Exception):          # duplicates: leaves an invalid unique index
            self.conn.execute("CREATE UNIQUE INDEX CONCURRENTLY idx_test_code_uq ON idx_test (code)")
        self.conn.autocommit = False
        try:
            with self.conn.cursor(row_factory=dict_row) as cur:
                index_rows = cur.execute((collectors / "index_usage_snapshot.sql").read_text()).fetchall()
                schema_rows = cur.execute((collectors / "schema_privileges_snapshot.sql").read_text()).fetchall()
                role_rows = cur.execute((collectors / "roles_snapshot.sql").read_text()).fetchall()
            invalid = [r for r in index_rows if r["index_name"] == "idx_test_code_uq"]
            self.assertEqual([(r["is_valid"], r["is_unique"]) for r in invalid], [(False, True)])
            # The same server stands in for every node; the primary is node-1.
            for node in (self.node1, self.node2, self.node3):
                rows = [dict(r, in_recovery=(node != self.node1) if r["record_type"] == "DATABASE"
                             else None) for r in index_rows]
                worker.save_index_usage_snapshot(self.conn, {"target_id": node,
                                                             "collector_key": "PG_INDEX_USAGE"}, rows)
            worker.save_schema_privileges_snapshot(
                self.conn, {"target_id": self.system, "collector_key": "PG_SCHEMA_PRIVILEGES"}, schema_rows)
            worker.save_roles_snapshot(self.conn, {"target_id": self.system, "collector_key": "PG_ROLES"},
                                       role_rows)
            self.conn.execute("UPDATE keystone.rule_parameter SET parameter_value = 0 "
                              "WHERE parameter_key = 'min_index_size'")
            self.conn.commit()

            # Statistics just started: unused indexes are not judged yet.
            engine.run_assessment(self.conn, "PG_INDEX_HEALTH", self.system)
            outcomes = self.latest_outcomes()
            self.assertEqual(outcomes["PG-IDX-001"][0], "INSUFFICIENT_EVIDENCE")
            self.assertIn("[statistics_too_recent]", outcomes["PG-IDX-001"][2])
            self.assertEqual(outcomes["PG-IDX-002"][:2], ("ATTENTION_REQUIRED", "CRITICAL"))

            self.conn.execute("UPDATE postgresql.index_usage_snapshot SET stats_since = captured_at - "
                              "interval '30 days' WHERE record_type = 'DATABASE'")
            self.conn.commit()
            engine.run_assessment(self.conn, "PG_INDEX_HEALTH", self.system)
            self.assertEqual(self.latest_outcomes()["PG-IDX-001"][:2], ("ATTENTION_REQUIRED", "WARNING"))
            unused = {r["subject_identifier"] for r in self.conn.execute(
                "SELECT subject_identifier FROM keystone.finding WHERE assessment_run_id = "
                "(SELECT max(assessment_run_id) FROM keystone.assessment_run) AND title = 'Unused Index'")}
            self.assertIn(f"{self.conn.info.dbname}.public.idx_test_unused", unused)
            self.assertNotIn(f"{self.conn.info.dbname}.public.idx_test_ext_id", unused)

            engine.run_assessment(self.conn, "PG_SECURITY_HEALTH", self.system)
            outcomes = self.latest_outcomes()
            self.assertEqual(outcomes["PG-SEC-001"][:2], ("ATTENTION_REQUIRED", "WARNING"))
            self.assertEqual(outcomes["PG-SEC-004"][:2], ("ATTENTION_REQUIRED", "WARNING"))
            subjects = {r["subject_identifier"] for r in self.conn.execute(
                "SELECT subject_identifier FROM keystone.finding WHERE assessment_run_id = "
                "(SELECT max(assessment_run_id) FROM keystone.assessment_run)")}
            self.assertEqual(subjects, {"idx_test_admin", f"{self.conn.info.dbname}.public"})
        finally:
            self.conn.rollback()
            self.conn.autocommit = True
            self.conn.execute("ALTER EXTENSION plpgsql DROP TABLE idx_test_ext")
            self.conn.execute("DROP TABLE IF EXISTS idx_test, idx_test_ext")
            self.conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            self.conn.execute("DROP ROLE IF EXISTS idx_test_admin")
            self.conn.autocommit = False

    def test_sequence_collector_feeds_the_rule_and_needs_the_privilege(self):
        from psycopg.rows import dict_row
        from repository.intelligence import assessment_engine as engine
        from repository.worker import worker
        sql = Path("providers/postgresql/telemetry/collectors/sequence_capacity_snapshot.sql").read_text()
        self.conn.commit()
        self.conn.autocommit = True
        for statement in (
                "CREATE TABLE seq_test (id serial PRIMARY KEY)",                   # integer column
                "SELECT setval('seq_test_id_seq', 2000000000)",                    # 93 %
                "CREATE TABLE seq_test_big (id bigint GENERATED ALWAYS AS IDENTITY)",
                "CREATE ROLE seq_test_monitor IN ROLE pg_monitor"):
            self.conn.execute(statement)
        self.conn.autocommit = False
        try:
            with self.conn.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(sql).fetchall()
                cur.execute("SET ROLE seq_test_monitor")
                monitor_rows = cur.execute(sql).fetchall()
                cur.execute("RESET ROLE")
            ours = {r["sequence_name"]: r for r in rows if r["record_type"] == "SEQUENCE"}
            self.assertEqual((ours["seq_test_id_seq"]["column_type"], ours["seq_test_id_seq"]["last_value"]),
                             ("integer", 2000000000))
            self.assertEqual(ours["seq_test_big_id_seq"]["table_name"], "seq_test_big")   # identity
            self.assertFalse(any(r["is_readable"] for r in monitor_rows if r["record_type"] == "SEQUENCE"))

            task = {"target_id": self.system, "collector_key": "PG_SEQUENCE_CAPACITY"}
            worker.save_sequence_capacity_snapshot(self.conn, task, rows)
            self.conn.commit()
            engine.run_assessment(self.conn, "PG_CAPACITY_HEALTH", self.system)
            self.assertEqual(self.latest_outcomes()["PG-CAP-002"][:2], ("ATTENTION_REQUIRED", "CRITICAL"))

            # pg_monitor alone cannot read the values: not assessed, and the reason says why.
            self.conn.execute("DELETE FROM postgresql.sequence_capacity_snapshot")
            worker.save_sequence_capacity_snapshot(self.conn, task, monitor_rows)
            self.conn.commit()
            engine.run_assessment(self.conn, "PG_CAPACITY_HEALTH", self.system)
            outcome, _, reason = self.latest_outcomes()["PG-CAP-002"]
            self.assertEqual(outcome, "INSUFFICIENT_EVIDENCE")
            self.assertIn("SELECT", report.explain_reason(reason, {"collections": []}, report.TEXTS["tr"]))
        finally:
            self.conn.rollback()
            self.conn.autocommit = True
            self.conn.execute("DROP TABLE IF EXISTS seq_test, seq_test_big")
            self.conn.execute("DROP ROLE IF EXISTS seq_test_monitor")
            self.conn.autocommit = False

    def test_reason_with_values_is_explained(self):
        t = report.TEXTS["tr"]
        reason = ('PG_INDEX_USAGE: [index_usage_incomplete] 3 index(es) unused on the reachable nodes; '
                  'not collected on postgre-2. {"count": 3, "nodes": "postgre-2"}')
        self.assertEqual(report.explain_reason(reason, {"collections": []}, t),
                         "3 index erişilebilen sunucularda hiç kullanılmamış görünüyor, ama postgre-2 "
                         "sunucusundan index kullanımı toplanamadığı için kesin değil.")

    def test_last_failover_in_the_inventory_and_findings_in_turkish(self):
        check_id = self.make_check()
        self.conn.execute(
            "INSERT INTO postgresql.wal_status_snapshot (target_id, captured_at, in_recovery, "
            "archive_mode, timeline_id, timeline_history_file, timeline_started_at) "
            "VALUES (%s, now(), FALSE, 'on', 126, '0000007E.history', now() - interval '3 hours 5 minutes'),"
            " (%s, now(), TRUE, 'on', NULL, NULL, NULL)", (self.node1, self.node2))
        self.conn.execute("UPDATE keystone.finding SET template_values = %s",
                          ('{"gid": "tm-1", "database_name": "orders", "owner": "app", '
                           '"age_seconds": 7500}',))
        self.conn.execute("UPDATE keystone.finding SET rule_id = (SELECT rule_id FROM "
                          "keystone.rule_definition WHERE rule_key = 'PG-TRAN-005')")
        self.conn.commit()
        page = self.render(check_id, "tr")
        executive = page[:page.index(TECH_PANEL)]
        self.assertIn("Son failover", executive)
        self.assertIn("3 saat 5 dakika önce", executive)
        self.assertIn("timeline 126", executive)
        self.assertIn("bekleme süresi: 2 saat 5 dakika.", page)
        self.assertIn("for 2 hours 5 minutes.", self.render(check_id, "en"))

    def test_last_failover_is_hidden_when_not_collected_in_this_check(self):
        check_id = self.make_check()
        self.conn.execute(
            "INSERT INTO postgresql.wal_status_snapshot (target_id, captured_at, in_recovery, "
            "archive_mode, timeline_id) VALUES (%s, now(), FALSE, 'on', 1)", (self.node1,))
        self.conn.execute("UPDATE keystone.health_check_collection SET status = 'FAILED' "
                          "WHERE health_check_id = %s AND collector_key = 'PG_WAL_STATUS'", (check_id,))
        self.conn.commit()
        self.assertNotIn("Son failover", self.render(check_id, "tr"))

    def test_finding_sentence_in_the_report_language(self):
        check_id = self.make_check()
        self.conn.execute("UPDATE keystone.finding SET template_values = %s",
                          ('{"pid": 4711, "duration_seconds": "1200.0", "dead_rows": 50000}',))
        self.conn.commit()
        self.assertIn("4711 numaralı session 1200.0 saniyedir transaction içinde boşta bekliyor.",
                      self.render(check_id, "tr"))
        self.assertIn("Session 4711 has been idle in transaction for 1200.0 seconds.",
                      self.render(check_id, "en"))
        self.assertEqual(report.template_value_text("dead_rows", 50000), "50,000")

    def test_finding_without_values_keeps_the_stored_text(self):
        page = self.render(self.make_check(), "tr")
        self.assertIn("Session 4711 idle &lt;script&gt;", page)

    def test_setting_values_are_readable(self):
        t = report.TEXTS["tr"]
        self.assertEqual(report.setting_value_text("32768", "8kB", t), "32768 (256.0 MB)")
        self.assertEqual(report.setting_value_text("off", None, t), "off")
        self.assertEqual(report.setting_value_text("300000", "ms", t), "300000 (5 dakika)")

    def test_no_problems_found_is_scoped_to_evaluated_rules(self):
        check_id = self.make_check()
        self.conn.execute(
            "UPDATE keystone.assessment_result res SET outcome = 'HEALTHY', reason = NULL "
            "FROM keystone.rule_definition rd WHERE rd.rule_id = res.rule_id "
            "AND rd.rule_key = 'PG-CONN-001'")
        self.conn.commit()
        page = self.render(check_id, "tr")
        executive = page[:page.index(TECH_PANEL)]
        self.assertIn("Sorun bulunmadı", executive)
        self.assertNotIn("Sorun yok", executive)
        self.assertIn("Yalnızca bu kontrolde değerlendirilen kurallara göre.", executive)

    def test_data_disk_is_the_longest_matching_mount(self):
        node = {"target_id": 1, "data_directory": "/var/lib/pgsql/data"}
        storage = [{"target_id": 1, "mount_point": "/", "total_bytes": 10},
                   {"target_id": 1, "mount_point": "/var/lib/pg", "total_bytes": 10},
                   {"target_id": 1, "mount_point": "/var/lib/pgsql", "total_bytes": 10},
                   {"target_id": 2, "mount_point": "/var/lib/pgsql/data", "total_bytes": 10}]
        self.assertEqual(report.data_disk(node, storage)["mount_point"], "/var/lib/pgsql")
        self.assertIsNone(report.data_disk({"target_id": 1, "data_directory": None}, storage))
        windows = {"target_id": 3, "data_directory": "C:/Program Files/PostgreSQL/17/data"}
        self.assertIsNone(report.data_disk(windows, storage))

    def test_large_estate_shows_totals_only(self):
        t = report.TEXTS["tr"]
        nodes, storage = [], []
        for i in range(30):
            nodes.append({"target_id": i, "name": f"pg-{i:02d}", "server_version": "17.10",
                          "in_recovery": i % 3 != 0, "logical_cpu_count": 8,
                          "memory_total_bytes": 32 * 1024 ** 3,
                          "data_directory": "/data/pg"})
            storage.append({"target_id": i, "node_name": f"pg-{i:02d}", "mount_point": "/data",
                            "used_bytes": 40 * 1024 ** 3, "total_bytes": 100 * 1024 ** 3})
        html = report.render_inventory({"nodes": nodes, "storage": storage, "databases": []}, t)
        self.assertNotIn("<table>", html)
        self.assertIn("10 primary, 20 replica", html)
        self.assertIn("240 çekirdek", html)
        self.assertIn("%40 dolu", html)                           # data disks only
        self.assertIn("Teknik Detaylar bölümünde", html)

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
