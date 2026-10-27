"""One-command health check: planning, queueing, waiting, assessment linkage (MVP Plan Phase 1).

Collectors are replaced by a fake task processor that writes run history, so
no monitored database is needed.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_health_check.py -v
"""

import contextlib
from datetime import datetime, timezone
import io
import time
import unittest
from unittest.mock import patch
import uuid

from psycopg import sql
from psycopg.rows import dict_row

from repository.healthcheck import health_check as hc
from repository.install import install as installer
from repository.worker import worker
from test_installer_findings import DisposablePostgres


class HealthCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)

        cls.template = "health_check_template_" + uuid.uuid4().hex
        with cls.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.template)))
        with patch.object(installer, "connect_repository",
                          lambda: cls.server.connect(cls.template)), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()

    def setUp(self):
        self.database = "health_check_" + uuid.uuid4().hex
        with self.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(self.database), sql.Identifier(self.template)))
        self.conn = self.connect()
        self.addCleanup(self.conn.close)

        self.system = self.add_target("cluster", "SYSTEM")
        self.node1 = self.add_target("node-1", "NODE", parent=self.system, host=True)
        self.node2 = self.add_target("node-2", "NODE", parent=self.system)
        self.node3 = self.add_target("node-3", "NODE", parent=self.system, sql_connection=False)

        self.failing = set()      # collector keys whose fake run fails
        self.slow = {}            # collector key -> seconds
        self.processed = []

    def connect(self):
        return self.server.connect(self.database, row_factory=dict_row)

    def add_target(self, name, target_type, parent=None, host=False, sql_connection=True):
        target_id = self.conn.execute(
            "INSERT INTO keystone.target (name, provider, target_type, environment, "
            "parent_target_id) VALUES (%s, 'PostgreSQL', %s, 'TEST', %s) RETURNING target_id",
            (name, target_type, parent)).fetchone()["target_id"]
        purposes = (["PRIMARY"] if sql_connection else []) + (["HOST"] if host else [])
        for purpose in purposes:
            self.conn.execute(
                "INSERT INTO keystone.target_connection (target_id, connection_name, host, port, "
                "database_name, username, auth_type, credential_data, connection_purpose) "
                "VALUES (%s, %s, 'h', 5432, 'postgres', 'u', 'PASSWORD', 'x', %s)",
                (target_id, purpose.lower(), purpose))
        self.conn.commit()
        return target_id

    def assign(self, target_id, collector_key, mode="ON_DEMAND"):
        self.conn.execute(
            "INSERT INTO keystone.collector_assignment (collector_id, target_id, execution_mode, "
            "interval_seconds, is_enabled) SELECT collector_id, %s, %s, %s, TRUE "
            "FROM keystone.collector_definition WHERE collector_key = %s",
            (target_id, mode, 60 if mode == "SCHEDULED" else None, collector_key))
        self.conn.commit()

    def fake_process(self, task):
        """Stands in for worker.process_task: history + dequeue, like a real run."""
        key = task["collector_key"]
        time.sleep(self.slow.get(key, 0))
        self.processed.append((task["target_id"], key))
        status = "CONNECTION_FAILED" if key in self.failing else "SUCCESS"
        with self.connect() as conn:
            worker.write_run_history(
                conn, task, task["started_at"], datetime.now(timezone.utc), status,
                error_message="connection refused" if key in self.failing else None)
            worker.remove_task(conn, task["task_id"], task["worker_id"])
            conn.commit()

    def run_check(self, **kwargs):
        with patch.object(worker, "connect_repository", self.connect), \
                self.assertLogs("keystone", level="INFO") as logs:
            check_id = hc.run_health_check(self.connect, self.system,
                                           process=self.fake_process, **kwargs)
        self.logs = logs.output
        return check_id

    def collections(self, check_id):
        return {(r["target_id"], r["collector_key"]): r for r in self.conn.execute(
            "SELECT * FROM keystone.health_check_collection WHERE health_check_id = %s",
            (check_id,)).fetchall()}

    # ------------------------------------------------------------------ tests

    def test_plan_covers_evidence_context_and_nodes(self):
        self.assign(self.node1, "PG_HOST_SNAPSHOT")
        check_id = self.run_check()
        got = self.collections(check_id)

        system_keys = {k for (t, k) in got if t == self.system}
        self.assertTrue({"PG_ACTIVITY_SNAPSHOT", "PG_CONNECTION_ACTIVITY",
                         "PG_REPLICATION_SLOTS", "PG_TRANSACTION_WRAPAROUND",
                         "PG_DATABASE_INVENTORY"} <= system_keys)
        self.assertNotIn("PG_INSTANCE_INVENTORY", system_keys)          # NODE scope
        for node in (self.node1, self.node2, self.node3):
            self.assertIn((node, "PG_INSTANCE_INVENTORY"), got)
        # Host snapshot is rule evidence (PG-CAP-001): planned on every node,
        # not collected where no SSH connection exists.
        self.assertEqual(got[(self.node1, "PG_HOST_SNAPSHOT")]["purpose"], "EVIDENCE")
        self.assertEqual(got[(self.node2, "PG_HOST_SNAPSHOT")]["status"], "NOT_COLLECTED")
        self.assertIn("no HOST connection", got[(self.node2, "PG_HOST_SNAPSHOT")]["status_message"])

    def test_missing_assignments_are_created_on_demand_only_with_a_connection(self):
        check_id = self.run_check()
        got = self.collections(check_id)

        modes = {r["execution_mode"] for r in self.conn.execute(
            "SELECT execution_mode FROM keystone.collector_assignment").fetchall()}
        self.assertEqual(modes, {"ON_DEMAND"})
        self.assertEqual(got[(self.node2, "PG_INSTANCE_INVENTORY")]["status"], "SUCCESS")

        no_connection = got[(self.node3, "PG_INSTANCE_INVENTORY")]
        self.assertEqual(no_connection["status"], "NOT_COLLECTED")
        self.assertIn("no database connection", no_connection["status_message"])
        self.assertNotIn((self.node3, "PG_INSTANCE_INVENTORY"), self.processed)

    def test_scheduled_assignment_is_used_and_keeps_its_mode(self):
        self.assign(self.system, "PG_ACTIVITY_SNAPSHOT", mode="SCHEDULED")
        self.run_check()
        mode = self.conn.execute(
            "SELECT execution_mode FROM keystone.collector_assignment ca "
            "JOIN keystone.collector_definition cd USING (collector_id) "
            "WHERE cd.collector_key = 'PG_ACTIVITY_SNAPSHOT'").fetchone()["execution_mode"]
        self.assertEqual(mode, "SCHEDULED")
        self.assertIn((self.system, "PG_ACTIVITY_SNAPSHOT"), self.processed)

    def test_failed_collector_does_not_stop_the_health_check(self):
        self.failing = {"PG_REPLICATION_SLOTS"}
        check_id = self.run_check()

        check = self.conn.execute("SELECT status FROM keystone.health_check "
                                  "WHERE health_check_id = %s", (check_id,)).fetchone()
        self.assertEqual(check["status"], "COMPLETED")
        failed = self.collections(check_id)[(self.system, "PG_REPLICATION_SLOTS")]
        self.assertEqual((failed["status"], failed["status_message"]),
                         ("CONNECTION_FAILED", "connection refused"))

    def test_assessments_run_and_are_linked_to_the_health_check(self):
        check_id = self.run_check()
        runs = self.conn.execute(
            "SELECT ad.assessment_key, ar.target_id FROM keystone.assessment_run ar "
            "JOIN keystone.assessment_definition ad USING (assessment_id) "
            "WHERE ar.health_check_id = %s ORDER BY 1", (check_id,)).fetchall()
        self.assertEqual([r["assessment_key"] for r in runs],
                         ["PG_BACKUP_HEALTH", "PG_CAPACITY_HEALTH", "PG_CONFIGURATION_HEALTH",
                          "PG_CONNECTION_HEALTH", "PG_INDEX_HEALTH", "PG_MAINTENANCE_HEALTH", "PG_REPLICATION_HEALTH",
                          "PG_SECURITY_HEALTH", "PG_TRANSACTION_HEALTH"])
        self.assertTrue(all(r["target_id"] == self.system for r in runs))

    def test_evidence_from_before_the_check_is_not_judged(self):
        # Lab 2026-10-21: postgre-1 was unreachable; its 1.5 h old settings produced findings.
        self.conn.execute(
            "INSERT INTO postgresql.configuration_snapshot (target_id, captured_at, setting_name, "
            "setting_value) VALUES (%s, now() - interval '90 minutes', 'ssl', 'off')", (self.node1,))
        self.conn.commit()
        self.failing = {"PG_CONFIGURATION_SNAPSHOT"}     # unreachable in this check
        check_id = self.run_check(assessment_key="PG_SECURITY_HEALTH")
        row = self.conn.execute(
            "SELECT res.outcome, res.finding_count FROM keystone.assessment_result res "
            "JOIN keystone.assessment_run ar USING (assessment_run_id) "
            "JOIN keystone.rule_definition rd USING (rule_id) "
            "WHERE ar.health_check_id = %s AND rd.rule_key = 'PG-SEC-003'", (check_id,)).fetchone()
        self.assertEqual((row["outcome"], row["finding_count"]), ("INSUFFICIENT_EVIDENCE", 0))

    def test_single_assessment_collects_only_its_evidence(self):
        check_id = self.run_check(assessment_key="PG_CONNECTION_HEALTH")
        evidence = {k for (t, k), r in self.collections(check_id).items()
                    if r["purpose"] == "EVIDENCE"}
        # PG-CONN-002 also needs the primary's configuration and the node roles.
        self.assertEqual(evidence, {"PG_CONNECTION_ACTIVITY", "PG_CONFIGURATION_SNAPSHOT",
                                    "PG_INSTANCE_INVENTORY"})

    def test_collector_past_the_wait_limit_is_not_waited_for(self):
        self.slow = {"PG_TRANSACTION_WRAPAROUND": 4}
        started = time.monotonic()
        check_id = self.run_check(wait_minutes=1.5 / 60)       # 1.5 s per collector

        row = self.collections(check_id)[(self.system, "PG_TRANSACTION_WRAPAROUND")]
        self.assertEqual(row["status"], "WAIT_LIMIT")
        self.assertIn("Still running", row["status_message"])
        # The command still waits for the thread at exit (it cannot be killed).
        self.assertGreaterEqual(time.monotonic() - started, 4)

    def test_already_queued_task_is_followed_not_duplicated(self):
        self.assign(self.system, "PG_ACTIVITY_SNAPSHOT")
        assignment = self.conn.execute(
            "SELECT assignment_id FROM keystone.collector_assignment").fetchone()["assignment_id"]
        task_id = self.conn.execute(
            "INSERT INTO keystone.collection_queue (assignment_id, status, scheduled_at) "
            "VALUES (%s, 'WAITING', now()) RETURNING task_id", (assignment,)).fetchone()["task_id"]
        self.conn.commit()

        check_id = self.run_check()
        self.assertEqual(self.collections(check_id)[(self.system, "PG_ACTIVITY_SNAPSHOT")]["task_id"],
                         task_id)

    def test_unknown_target_fails_before_creating_a_record(self):
        with self.assertRaises(ValueError):
            hc.run_health_check(self.connect, 999999)
        self.assertEqual(self.conn.execute(
            "SELECT count(*) AS n FROM keystone.health_check").fetchone()["n"], 0)

    def test_summary_prints_collections_and_rules(self):
        self.failing = {"PG_REPLICATION_SLOTS"}
        check_id = self.run_check()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            hc.print_summary(self.conn, check_id)
        text = out.getvalue()
        self.assertIn(f"Health check {check_id} - cluster - COMPLETED", text)
        self.assertIn("PG_REPLICATION_SLOTS", text)
        self.assertIn("CONNECTION_FAILED  (connection refused)", text)
        self.assertIn("PG-TRAN-001", text)


if __name__ == "__main__":
    unittest.main()
