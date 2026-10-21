"""Database-backed tests for assessment runs and assessment results (ADR-0014).

Each test gets a fresh copy of a fully installed repository, inserts the
evidence it needs, runs the real engine and inspects what was persisted:
assessment_result rows, findings and the assessment_run status.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_assessment_run.py -v

PostgreSQL server binaries are required (see test_installer_findings.py).
"""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import unittest
from unittest.mock import patch
import uuid

from psycopg import sql
from psycopg.rows import dict_row

from repository.install import install as installer
from repository.intelligence import assessment_engine as engine
from test_installer_findings import DisposablePostgres


EVALUATION_TIME = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)


class AssessmentRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)

        # Install once into a template database; every test copies it.
        cls.template = "assessment_template_" + uuid.uuid4().hex
        with cls.server.connect(autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.template))
            )

        def connect_template():
            return cls.server.connect(cls.template)

        with patch.object(installer, "connect_repository", connect_template), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()

    def setUp(self):
        self.database = "assessment_test_" + uuid.uuid4().hex
        with self.server.connect(autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(self.database),
                    sql.Identifier(self.template),
                )
            )

        self.conn = self.connect()
        self.addCleanup(self.conn.close)

        # The engine opens a fresh connection when it must record a failure
        # on an unusable connection; point it at this test database.
        patcher = patch.object(engine, "connect_repository", self.connect)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.target_id = self.conn.execute(
            """
            INSERT INTO keystone.target (name, provider, target_type, environment)
            VALUES ('test-target', 'PostgreSQL', 'SYSTEM', 'TEST')
            RETURNING target_id
            """
        ).fetchone()["target_id"]
        self.conn.commit()

    def connect(self):
        return self.server.connect(self.database, row_factory=dict_row)

    # ------------------------------------------------------------------ helpers

    def add_session(self, captured_at, state="active",
                    transaction_age=None, idle_for=None, pid=4242):
        transaction_start = (
            None if transaction_age is None
            else captured_at - timedelta(seconds=transaction_age)
        )
        state_change = (
            captured_at - timedelta(seconds=idle_for or 1)
        )
        self.conn.execute(
            """
            INSERT INTO postgresql.activity_snapshot
                (target_id, captured_at, pid, state, backend_type,
                 transaction_start, state_change)
            VALUES (%s, %s, %s, %s, 'client backend', %s, %s)
            """,
            (self.target_id, captured_at, pid, state,
             transaction_start, state_change),
        )
        self.conn.commit()

    def run_engine(self, assessment="PG_TRANSACTION_HEALTH", **kwargs):
        kwargs.setdefault("evaluation_time", EVALUATION_TIME)
        with contextlib.redirect_stdout(io.StringIO()):
            return engine.run_assessment(
                self.conn, assessment, self.target_id, **kwargs
            )

    def read_all(self, statement, params=()):
        # Separate, short-lived connection: only committed data is visible.
        with self.connect() as conn:
            return conn.execute(statement, params).fetchall()

    def read_one(self, statement, params=()):
        rows = self.read_all(statement, params)
        return rows[0] if rows else None

    def results(self, run_id):
        rows = self.read_all(
            """
            SELECT rd.rule_key, ar.outcome, ar.max_severity,
                   ar.finding_count, ar.reason
            FROM keystone.assessment_result ar
            JOIN keystone.rule_definition rd USING (rule_id)
            WHERE ar.assessment_run_id = %s
            """,
            (run_id,),
        )
        return {row["rule_key"]: row for row in rows}

    def run_row(self, run_id):
        return self.read_one(
            "SELECT status, status_message, finished_at "
            "FROM keystone.assessment_run WHERE assessment_run_id = %s",
            (run_id,),
        )

    def finding_count(self, run_id):
        return self.read_one(
            "SELECT count(*) AS n FROM keystone.finding "
            "WHERE assessment_run_id = %s",
            (run_id,),
        )["n"]

    # -------------------------------------------------------------------- tests

    def test_every_rule_gets_a_result_and_missing_evidence_is_visible(self):
        self.add_session(EVALUATION_TIME - timedelta(seconds=30))

        run_id = self.run_engine()
        results = self.results(run_id)

        self.assertEqual(set(results), {"PG-TRAN-001", "PG-TRAN-002", "PG-TRAN-003", "PG-TRAN-004"})
        self.assertEqual(results["PG-TRAN-004"]["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(results["PG-TRAN-001"]["outcome"], "HEALTHY")
        self.assertEqual(results["PG-TRAN-003"]["outcome"], "HEALTHY")
        # No wraparound evidence was collected: not healthy, not assessed.
        self.assertEqual(results["PG-TRAN-002"]["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("PG_TRANSACTION_WRAPAROUND", results["PG-TRAN-002"]["reason"])
        self.assertIn("not available", results["PG-TRAN-002"]["reason"])

        run = self.run_row(run_id)
        self.assertEqual(run["status"], "SUCCESS")
        self.assertIsNotNone(run["finished_at"])

    def test_attention_required_records_count_and_max_severity(self):
        captured_at = EVALUATION_TIME - timedelta(seconds=30)
        self.add_session(captured_at, state="idle in transaction",
                         transaction_age=4000, idle_for=1000)

        run_id = self.run_engine()
        results = self.results(run_id)

        for rule_key in ("PG-TRAN-001", "PG-TRAN-003"):
            with self.subTest(rule=rule_key):
                self.assertEqual(results[rule_key]["outcome"], "ATTENTION_REQUIRED")
                self.assertEqual(results[rule_key]["max_severity"], "CRITICAL")
                self.assertEqual(results[rule_key]["finding_count"], 1)
        self.assertEqual(self.finding_count(run_id), 2)

    def test_max_severity_is_the_highest_of_several_findings(self):
        captured_at = EVALUATION_TIME - timedelta(seconds=30)
        self.add_session(captured_at, state="idle in transaction",
                         transaction_age=400, idle_for=400, pid=1)
        self.add_session(captured_at, state="idle in transaction",
                         transaction_age=1000, idle_for=1000, pid=2)

        result = self.results(self.run_engine())["PG-TRAN-001"]

        self.assertEqual(result["finding_count"], 2)
        self.assertEqual(result["max_severity"], "CRITICAL")

    def test_stale_evidence_is_insufficient_with_its_age(self):
        self.add_session(EVALUATION_TIME - timedelta(seconds=700))

        result = self.results(self.run_engine())["PG-TRAN-001"]

        self.assertEqual(result["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("stale", result["reason"])
        self.assertIn("MaxAge=600s", result["reason"])

    def test_evaluation_time_decides_freshness(self):
        # Evidence captured two days ago, evaluated as of shortly after its
        # capture (offline evidence): fresh. Evaluated now: stale.
        captured_at = EVALUATION_TIME - timedelta(days=2)
        self.add_session(captured_at)

        as_of_capture = self.results(
            self.run_engine(evaluation_time=captured_at + timedelta(seconds=10))
        )["PG-TRAN-001"]
        as_of_now = self.results(self.run_engine())["PG-TRAN-001"]

        self.assertEqual(as_of_capture["outcome"], "HEALTHY")
        self.assertEqual(as_of_now["outcome"], "INSUFFICIENT_EVIDENCE")

    def test_failing_rule_is_isolated_and_run_is_partial(self):
        self.add_session(EVALUATION_TIME - timedelta(seconds=30),
                         state="idle in transaction",
                         transaction_age=4000, idle_for=1000)

        def broken_evaluator(rows, rule, thresholds):
            raise ValueError("boom")

        with patch.dict(engine.RULE_EVALUATORS, {"PG-TRAN-001": broken_evaluator}):
            run_id = self.run_engine()

        results = self.results(run_id)
        self.assertEqual(results["PG-TRAN-001"]["outcome"], "ERROR")
        self.assertEqual(results["PG-TRAN-001"]["reason"], "ValueError: boom")
        # Later rules still ran.
        self.assertEqual(results["PG-TRAN-003"]["outcome"], "ATTENTION_REQUIRED")

        run = self.run_row(run_id)
        self.assertEqual(run["status"], "PARTIAL")
        self.assertIn("1 rule(s)", run["status_message"])

    def test_failed_rule_findings_are_rolled_back_and_database_errors_recover(self):
        self.add_session(EVALUATION_TIME - timedelta(seconds=30))

        good = {
            "severity": "WARNING",
            "template_values": {"pid": 1, "duration_seconds": "1.0"},
            "observed_value": 1, "observed_unit": "SECOND",
            "subject_type": "SESSION", "subject_identifier": "1",
        }
        # The second finding violates the finding severity CHECK constraint:
        # a real database error after the first finding was inserted.
        bad = {**good, "severity": "NOT_A_SEVERITY"}

        def evaluator(rows, rule, thresholds):
            return [good, bad]

        with patch.dict(engine.RULE_EVALUATORS, {"PG-TRAN-001": evaluator}):
            run_id = self.run_engine()

        results = self.results(run_id)
        self.assertEqual(results["PG-TRAN-001"]["outcome"], "ERROR")
        self.assertIn("CheckViolation", results["PG-TRAN-001"]["reason"])
        self.assertEqual(self.finding_count(run_id), 0)
        # The connection recovered for the remaining rules.
        self.assertEqual(results["PG-TRAN-003"]["outcome"], "HEALTHY")
        self.assertEqual(self.run_row(run_id)["status"], "PARTIAL")

    def test_rule_without_evaluator_is_a_rule_error(self):
        self.add_session(EVALUATION_TIME - timedelta(seconds=30))
        evaluators = {
            key: value for key, value in engine.RULE_EVALUATORS.items()
            if key != "PG-TRAN-003"
        }

        with patch.object(engine, "RULE_EVALUATORS", evaluators):
            results = self.results(self.run_engine())

        self.assertEqual(results["PG-TRAN-003"]["outcome"], "ERROR")
        self.assertIn("No evaluator registered", results["PG-TRAN-003"]["reason"])
        self.assertEqual(results["PG-TRAN-001"]["outcome"], "HEALTHY")

    def test_engine_failure_marks_run_failed_and_reraises(self):
        with patch.object(engine, "load_rules",
                          side_effect=RuntimeError("dictionary unavailable")), \
                self.assertRaises(RuntimeError):
            self.run_engine()

        run = self.read_all(
            "SELECT assessment_run_id, status, status_message, finished_at "
            "FROM keystone.assessment_run"
        )
        self.assertEqual(len(run), 1)
        self.assertEqual(run[0]["status"], "FAILED")
        self.assertEqual(run[0]["status_message"],
                         "RuntimeError: dictionary unavailable")
        self.assertIsNotNone(run[0]["finished_at"])

    def test_engine_failure_with_lost_connection_uses_fresh_connection(self):
        def lose_connection(conn, assessment_id):
            conn.close()
            raise RuntimeError("connection lost")

        with patch.object(engine, "load_rules", side_effect=lose_connection), \
                self.assertRaises(RuntimeError):
            self.run_engine()

        run = self.read_one(
            "SELECT status, status_message FROM keystone.assessment_run"
        )
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["status_message"], "RuntimeError: connection lost")

    def test_database_rejects_inconsistent_results(self):
        run_id = self.run_engine()
        rule_id = self.read_one(
            "SELECT rule_id FROM keystone.rule_definition "
            "WHERE rule_key = 'PG-TRAN-001'"
        )["rule_id"]
        conn = self.connect()
        self.addCleanup(conn.close)

        with self.assertRaises(Exception) as caught:
            conn.execute(
                """
                INSERT INTO keystone.assessment_result
                    (assessment_run_id, rule_id, outcome, max_severity,
                     finding_count, evaluated_at)
                VALUES (%s, %s, 'HEALTHY', 'WARNING', 0, now())
                """,
                (run_id, rule_id),
            )
        self.assertIn("ck_assessment_result", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
