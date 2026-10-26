"""Assessment schedules, defaults, consistency warnings and the assessment job adapter (ADR-0015).

Run from the repository root:
    python -B -m unittest discover -s tests -p test_assessment_schedule.py -v
"""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from psycopg import sql
from psycopg.rows import dict_row

from repository.agent.jobs import AssessmentJobs
from repository.agent.scheduler import Scheduler
from repository.install import install as installer
from test_installer_findings import DisposablePostgres


class AssessmentScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)

        cls.template = "assess_sched_template_" + uuid.uuid4().hex
        with cls.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.template)))

        with patch.object(installer, "connect_repository",
                          lambda: cls.server.connect(cls.template)), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()

    def setUp(self):
        self.database = "assess_sched_" + uuid.uuid4().hex
        with self.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(self.database), sql.Identifier(self.template)))
        self.conn = self.connect()
        self.addCleanup(self.conn.close)

        self.target_id = self.conn.execute(
            "INSERT INTO keystone.target (name, provider, target_type, environment) "
            "VALUES ('pg-test', 'PostgreSQL', 'SYSTEM', 'TEST') RETURNING target_id"
        ).fetchone()["target_id"]
        self.conn.commit()

    def connect(self):
        return self.server.connect(self.database, row_factory=dict_row)

    def apply_defaults(self):
        created = self.conn.execute(
            "SELECT keystone.apply_default_assessment_schedules(%s) AS n",
            (self.target_id,)).fetchone()["n"]
        self.conn.commit()
        return created

    def schedule_collector(self, collector_key, interval):
        self.conn.execute(
            """
            INSERT INTO keystone.collector_assignment
                (collector_id, target_id, execution_mode, interval_seconds, is_enabled)
            SELECT collector_id, %s, 'SCHEDULED', %s, TRUE
            FROM keystone.collector_definition WHERE collector_key = %s
            """, (self.target_id, interval, collector_key))
        self.conn.commit()

    def warnings(self):
        return {(r["rule_key"], r["evidence_source"], r["problem"]) for r in self.conn.execute(
            "SELECT * FROM keystone.schedule_consistency_warning WHERE target_id = %s",
            (self.target_id,)).fetchall()}

    def required_sources(self):
        return {r["evidence_source"] for r in self.conn.execute(
            """
            SELECT DISTINCT rer.evidence_source
            FROM keystone.rule_evidence_requirement rer
            JOIN keystone.rule_definition rd USING (rule_id)
            WHERE rd.is_enabled AND rer.is_required
            """).fetchall()}

    # ---------------------------------------------------------------- defaults

    def test_defaults_create_one_schedule_per_assessment_and_are_idempotent(self):
        created = self.apply_defaults()
        self.assertEqual(created, 8)
        self.assertEqual(self.apply_defaults(), 0)

        rows = self.conn.execute(
            "SELECT ad.assessment_key, s.interval_seconds, s.offset_seconds "
            "FROM keystone.assessment_schedule s JOIN keystone.assessment_definition ad "
            "USING (assessment_id) WHERE s.target_id = %s", (self.target_id,)).fetchall()
        self.assertEqual({r["assessment_key"]: r["interval_seconds"] for r in rows},
                         {"PG_CONNECTION_HEALTH": 300, "PG_REPLICATION_HEALTH": 300,
                          "PG_TRANSACTION_HEALTH": 300, "PG_CAPACITY_HEALTH": 900,
                          "PG_CONFIGURATION_HEALTH": 3600, "PG_BACKUP_HEALTH": 3600,
                          "PG_SECURITY_HEALTH": 3600, "PG_MAINTENANCE_HEALTH": 3600})
        self.assertTrue(all(r["offset_seconds"] == 30 for r in rows))

    def test_offset_must_be_shorter_than_interval(self):
        self.apply_defaults()
        with self.assertRaises(Exception):
            self.conn.execute("UPDATE keystone.assessment_schedule SET offset_seconds = 300")
        self.conn.rollback()

    # ---------------------------------------------------------------- warnings

    def test_unscheduled_collectors_are_reported(self):
        self.apply_defaults()
        reported = {source for _, source, problem in self.warnings()
                    if problem == "NOT_SCHEDULED"}
        self.assertEqual(reported, self.required_sources())

    def test_interval_longer_than_freshness_is_reported(self):
        self.apply_defaults()
        self.schedule_collector("PG_ACTIVITY_SNAPSHOT", 900)    # freshness 600

        problems = {problem for _, source, problem in self.warnings()
                    if source == "PG_ACTIVITY_SNAPSHOT"}
        self.assertEqual(problems, {"INTERVAL_TOO_LONG"})

    def test_well_configured_target_has_no_warnings(self):
        self.apply_defaults()
        for source in self.required_sources():
            self.schedule_collector(source, 60)
        self.assertEqual(self.warnings(), set())

    def test_no_schedule_no_warning(self):
        self.assertEqual(self.warnings(), set())

    # ----------------------------------------------------------------- adapter

    def test_due_assessment_runs_in_background_with_planned_time(self):
        self.apply_defaults()
        calls = []
        release = threading.Event()

        def fake_run(conn, assessment_key, target_id, scheduled_at=None):
            calls.append((assessment_key, target_id, scheduled_at))
            release.wait(5)

        jobs = AssessmentJobs(connect=self.connect, run_assessment=fake_run)
        self.addCleanup(jobs.shutdown)
        self.addCleanup(release.set)
        # Exactly on a slot (hh:m0:30): no catch-up, so only on-time runs start.
        slot = datetime(2026, 10, 14, 12, 0, 30, tzinfo=timezone.utc)
        scheduler = Scheduler([jobs], clock=lambda: slot)

        dispatched = scheduler.tick(self.conn)
        self.assertEqual(len(dispatched), 8)

        deadline = time.monotonic() + 5
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(calls), 2)                 # pool of 2: the rest waits

        # Still running: listed as busy, not dispatched again.
        self.assertTrue(all(item.is_busy for item in jobs.list_items(self.conn)))
        self.assertEqual({c[2] for c in calls}, {slot})
        self.conn.commit()

    def test_assessments_do_not_catch_up_after_start(self):
        self.apply_defaults()
        late = datetime(2026, 10, 14, 12, 2, 37, tzinfo=timezone.utc)   # slot 12:00:30
        jobs = AssessmentJobs(run_assessment=lambda *a, **k: None)
        self.addCleanup(jobs.shutdown)

        self.assertEqual(Scheduler([jobs], clock=lambda: late).tick(self.conn), [])

    def test_last_run_comes_from_assessment_run(self):
        self.apply_defaults()
        now = datetime.now(timezone.utc)
        self.conn.execute(
            """
            INSERT INTO keystone.assessment_run (assessment_id, target_id, started_at,
                                                 finished_at, status)
            SELECT assessment_id, %s, %s, %s, 'SUCCESS'
            FROM keystone.assessment_definition WHERE assessment_key = 'PG_CONNECTION_HEALTH'
            """, (self.target_id, now - timedelta(seconds=5), now))
        self.conn.commit()

        items = {item.key[0]: item for item in AssessmentJobs().list_items(self.conn)}
        self.assertEqual(items["PG_CONNECTION_HEALTH"].last_finished_at, now)
        self.assertEqual(items["PG_CONNECTION_HEALTH"].offset_seconds, 30)
        self.assertIsNone(items["PG_TRANSACTION_HEALTH"].last_started_at)

    def test_start_hook_fails_abandoned_runs_and_logs_warnings(self):
        self.apply_defaults()
        self.conn.execute(
            """
            INSERT INTO keystone.assessment_run (assessment_id, target_id, started_at, status)
            SELECT assessment_id, %s, now() - interval '2 hours', 'RUNNING'
            FROM keystone.assessment_definition WHERE assessment_key = 'PG_CONNECTION_HEALTH'
            """, (self.target_id,))
        self.conn.commit()

        with self.assertLogs("keystone.jobs", level="WARNING") as logs:
            AssessmentJobs().on_start(self.conn)
            self.conn.commit()

        status = self.conn.execute("SELECT status FROM keystone.assessment_run").fetchone()
        self.assertEqual(status["status"], "FAILED")
        self.assertTrue(any("abandoned" in line for line in logs.output))
        self.assertTrue(any("NOT_SCHEDULED" in line for line in logs.output))

    def test_engine_stores_scheduled_at(self):
        from repository.intelligence import assessment_engine
        planned = datetime(2026, 10, 14, 12, 0, 30, tzinfo=timezone.utc)
        with self.assertLogs("keystone.assessment_engine", level="INFO"):
            run_id = assessment_engine.run_assessment(
                self.conn, "PG_CONNECTION_HEALTH", self.target_id, scheduled_at=planned)
        stored = self.conn.execute(
            "SELECT scheduled_at FROM keystone.assessment_run WHERE assessment_run_id = %s",
            (run_id,)).fetchone()["scheduled_at"]
        self.assertEqual(stored, planned)

    def test_engine_logs_one_summary_line_per_run_at_info(self):
        from repository.intelligence import assessment_engine
        with self.assertLogs("keystone.assessment_engine", level="INFO") as logs:
            run_id = assessment_engine.run_assessment(
                self.conn, "PG_TRANSACTION_HEALTH", self.target_id)

        info = [r.getMessage() for r in logs.records if r.levelname == "INFO"]
        self.assertEqual(info, [
            f"Assessment run {run_id} PG_TRANSACTION_HEALTH on target {self.target_id}"
            " -> SUCCESS: 5 INSUFFICIENT_EVIDENCE"
        ])

    def test_engine_stores_thresholds_used(self):
        from repository.intelligence import assessment_engine
        with self.assertLogs("keystone.assessment_engine", level="INFO"):
            run_id = assessment_engine.run_assessment(
                self.conn, "PG_TRANSACTION_HEALTH", self.target_id)
        rows = {r["rule_key"]: r["thresholds_used"] for r in self.conn.execute(
            "SELECT rd.rule_key, res.thresholds_used FROM keystone.assessment_result res "
            "JOIN keystone.rule_definition rd USING (rule_id) WHERE res.assessment_run_id = %s",
            (run_id,)).fetchall()}
        self.assertEqual(
            sorted((t["severity"], t["value"], t["unit"]) for t in rows["PG-TRAN-001"]),
            [("CRITICAL", 900.0, "SECOND"), ("WARNING", 300.0, "SECOND")])


if __name__ == "__main__":
    unittest.main()
