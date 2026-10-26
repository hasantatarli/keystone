"""Unit tests for rule evaluators and evidence freshness validation.

These tests exercise the PostgreSQL engineering logic directly, without a
database. Rows and thresholds use the same shapes and types the repository
returns (thresholds carry Decimal values from NUMERIC columns).

They also cover paths the lab cannot realistically produce, such as the
PG-TRAN-002 transaction ID age thresholds.

Thresholds are deliberately passed in ascending order in several tests:
evaluators must select the highest matching threshold regardless of the order
in which thresholds are supplied.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_rule_evaluators.py -v
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from repository.intelligence import assessment_engine as engine


NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


def threshold(severity, value, unit):
    return {
        "threshold_id": None,
        "severity": severity,
        "threshold_value": Decimal(str(value)),
        "threshold_unit": unit,
    }


def rule(default_severity=None):
    return {"default_severity": default_severity}


def severities(findings):
    return [finding["severity"] for finding in findings]


# Keystone engineering defaults, in ascending order on purpose.
IDLE_TRANSACTION_THRESHOLDS = [
    threshold("WARNING", 300, "SECOND"),
    threshold("CRITICAL", 900, "SECOND"),
]
XID_THRESHOLDS = [
    threshold("WARNING", 1_500_000_000, "TRANSACTION"),
    threshold("CRITICAL", 1_800_000_000, "TRANSACTION"),
]
LONG_RUNNING_THRESHOLDS = [
    threshold("WARNING", 1800, "SECOND"),
    threshold("CRITICAL", 3600, "SECOND"),
]
ABORTED_CONNECTION_THRESHOLDS = [
    threshold("WARNING", 1, "CONNECTION"),
]


class LongIdleTransactionTests(unittest.TestCase):
    """PG-TRAN-001"""

    def session(self, idle_seconds, transaction_age_seconds=None, **overrides):
        # By default the transaction became idle right after it started.
        if transaction_age_seconds is None:
            transaction_age_seconds = idle_seconds
        row = {
            "snapshot_id": 1,
            "captured_at": NOW,
            "pid": 4242,
            "backend_type": "client backend",
            "state": "idle in transaction",
            "transaction_start": NOW - timedelta(seconds=transaction_age_seconds),
            "state_change": NOW - timedelta(seconds=idle_seconds),
        }
        row.update(overrides)
        return row

    def evaluate(self, *rows, thresholds=IDLE_TRANSACTION_THRESHOLDS):
        return engine.evaluate_long_idle_transaction(
            list(rows), rule(), thresholds
        )

    def test_below_warning_threshold_produces_no_finding(self):
        self.assertEqual(self.evaluate(self.session(299.9)), [])

    def test_exactly_warning_threshold_is_warning(self):
        self.assertEqual(severities(self.evaluate(self.session(300))), ["WARNING"])

    def test_between_thresholds_is_warning(self):
        self.assertEqual(severities(self.evaluate(self.session(372))), ["WARNING"])

    def test_exactly_critical_threshold_is_critical(self):
        self.assertEqual(severities(self.evaluate(self.session(900))), ["CRITICAL"])

    def test_above_critical_threshold_is_critical(self):
        self.assertEqual(severities(self.evaluate(self.session(950))), ["CRITICAL"])

    def test_finding_carries_who_and_where(self):
        finding = self.evaluate(self.session(
            950, application_name="billing-api", user_name="app_user",
            client_addr="10.0.5.21", database_name="orders",
            query_text="UPDATE   invoices\n SET paid = true"))[0]
        expected = {
            "application": "billing-api", "user": "app_user", "client_addr": "10.0.5.21",
            "database": "orders", "state": "idle in transaction",
            "last_query": "UPDATE invoices SET paid = true",
            "captured_at": NOW.isoformat(),
            "state_change": (NOW - timedelta(seconds=950)).isoformat(),
            "transaction_start": (NOW - timedelta(seconds=950)).isoformat(),
        }
        self.assertEqual(finding["details"], expected)

    def test_last_query_is_trimmed(self):
        finding = self.evaluate(self.session(950, query_text="SELECT " + "x" * 500))[0]
        self.assertEqual(len(finding["details"]["last_query"]),
                         engine.QUERY_PREVIEW_CHARS + 3)

    def test_threshold_order_does_not_change_severity(self):
        for thresholds in (IDLE_TRANSACTION_THRESHOLDS,
                           list(reversed(IDLE_TRANSACTION_THRESHOLDS))):
            with self.subTest(order=[t["severity"] for t in thresholds]):
                self.assertEqual(
                    severities(self.evaluate(self.session(950),
                                             thresholds=thresholds)),
                    ["CRITICAL"],
                )

    def test_finding_describes_the_session(self):
        finding = self.evaluate(self.session(372))[0]
        self.assertEqual(finding["subject_type"], "SESSION")
        self.assertEqual(finding["subject_identifier"], "4242")
        self.assertEqual(finding["observed_unit"], "SECOND")
        self.assertAlmostEqual(finding["observed_value"], 372)
        self.assertEqual(finding["template_values"],
                         {"pid": 4242, "duration_seconds": "372.0"})

    def test_non_client_backends_are_ignored(self):
        row = self.session(950, backend_type="autovacuum worker")
        self.assertEqual(self.evaluate(row), [])

    def test_other_states_are_ignored(self):
        for state in ("active", "idle", None):
            with self.subTest(state=state):
                self.assertEqual(self.evaluate(self.session(950, state=state)), [])

    def test_aborted_idle_transactions_are_not_covered(self):
        # Current, documented behaviour (DEVELOPMENT_STATUS known issue 10):
        # aborted sessions are reported only by PG-CONN-001, without duration.
        row = self.session(950, state="idle in transaction (aborted)")
        self.assertEqual(self.evaluate(row), [])

    def test_missing_state_change_is_ignored(self):
        row = self.session(950, state_change=None)
        self.assertEqual(self.evaluate(row), [])

    def test_duration_is_idle_time_not_transaction_age(self):
        # Worked for ten minutes, idle for one minute: idle for one minute.
        row = self.session(60, transaction_age_seconds=660)
        self.assertEqual(self.evaluate(row), [])

    def test_long_idle_after_long_work_uses_idle_time_for_severity(self):
        # Idle for 400 s inside a 2000 s old transaction: WARNING, not CRITICAL.
        finding = self.evaluate(self.session(400, transaction_age_seconds=2000))[0]
        self.assertEqual(finding["severity"], "WARNING")
        self.assertAlmostEqual(finding["observed_value"], 400)

    def test_each_matching_session_produces_its_own_finding(self):
        findings = self.evaluate(
            self.session(100, pid=1),
            self.session(400, pid=2),
            self.session(1000, pid=3),
        )
        self.assertEqual(
            [(f["subject_identifier"], f["severity"]) for f in findings],
            [("2", "WARNING"), ("3", "CRITICAL")],
        )

    def test_thresholds_with_other_units_are_ignored(self):
        thresholds = [threshold("CRITICAL", 1, "TRANSACTION")]
        self.assertEqual(self.evaluate(self.session(950), thresholds=thresholds), [])


class LongRunningTransactionTests(unittest.TestCase):
    """PG-TRAN-003"""

    def session(self, transaction_age_seconds, state="active", **overrides):
        row = {
            "snapshot_id": 1,
            "captured_at": NOW,
            "pid": 5151,
            "backend_type": "client backend",
            "state": state,
            "transaction_start": NOW - timedelta(seconds=transaction_age_seconds),
            "state_change": NOW - timedelta(seconds=5),
        }
        row.update(overrides)
        return row

    def evaluate(self, *rows, thresholds=LONG_RUNNING_THRESHOLDS):
        return engine.evaluate_long_running_transaction(
            list(rows), rule(), thresholds
        )

    def test_below_warning_threshold_produces_no_finding(self):
        self.assertEqual(self.evaluate(self.session(1799.9)), [])

    def test_exactly_warning_threshold_is_warning(self):
        self.assertEqual(severities(self.evaluate(self.session(1800))), ["WARNING"])

    def test_exactly_critical_threshold_is_critical(self):
        self.assertEqual(severities(self.evaluate(self.session(3600))), ["CRITICAL"])

    def test_threshold_order_does_not_change_severity(self):
        for thresholds in (LONG_RUNNING_THRESHOLDS,
                           list(reversed(LONG_RUNNING_THRESHOLDS))):
            with self.subTest(order=[t["severity"] for t in thresholds]):
                self.assertEqual(
                    severities(self.evaluate(self.session(4000),
                                             thresholds=thresholds)),
                    ["CRITICAL"],
                )

    def test_any_working_or_idle_state_is_measured(self):
        for state in ("active", "idle in transaction", "fastpath function call"):
            with self.subTest(state=state):
                self.assertEqual(
                    severities(self.evaluate(self.session(2000, state=state))),
                    ["WARNING"],
                )

    def test_aborted_transactions_are_excluded(self):
        # Covered by PG-CONN-001; the failed top-level transaction has
        # already released its snapshot and locks.
        row = self.session(5000, state="idle in transaction (aborted)")
        self.assertEqual(self.evaluate(row), [])

    def test_sessions_without_transaction_are_ignored(self):
        self.assertEqual(self.evaluate(self.session(5000, state="idle",
                                                    transaction_start=None)), [])

    def test_non_client_backends_are_ignored(self):
        row = self.session(5000, backend_type="autovacuum worker")
        self.assertEqual(self.evaluate(row), [])

    def test_metric_is_transaction_age_not_idle_time(self):
        # Idle for 5 s inside a 2000 s old transaction: reported here,
        # while PG-TRAN-001 would report nothing.
        row = self.session(2000, state="idle in transaction")
        finding = self.evaluate(row)[0]
        self.assertAlmostEqual(finding["observed_value"], 2000)
        self.assertEqual(
            engine.evaluate_long_idle_transaction([row], rule(),
                                                  IDLE_TRANSACTION_THRESHOLDS),
            [],
        )

    def test_finding_describes_the_session_and_its_state(self):
        finding = self.evaluate(self.session(2000, state="active"))[0]
        self.assertEqual(finding["subject_type"], "SESSION")
        self.assertEqual(finding["subject_identifier"], "5151")
        self.assertEqual(finding["observed_unit"], "SECOND")
        self.assertEqual(
            finding["template_values"],
            {"pid": 5151, "duration_seconds": "2000.0", "state": "active"},
        )


class DatabaseXidWraparoundTests(unittest.TestCase):
    """PG-TRAN-002 (cannot be produced in the lab)."""

    def database(self, xid_age, name="appdb"):
        return {"snapshot_id": 1, "database_name": name, "xid_age": xid_age}

    def evaluate(self, *rows, thresholds=XID_THRESHOLDS):
        return engine.evaluate_database_xid_wraparound(
            list(rows), rule(), thresholds
        )

    def test_below_warning_threshold_produces_no_finding(self):
        self.assertEqual(self.evaluate(self.database(1_499_999_999)), [])

    def test_exactly_warning_threshold_is_warning(self):
        self.assertEqual(severities(self.evaluate(self.database(1_500_000_000))),
                         ["WARNING"])

    def test_exactly_critical_threshold_is_critical(self):
        self.assertEqual(severities(self.evaluate(self.database(1_800_000_000))),
                         ["CRITICAL"])

    def test_threshold_order_does_not_change_severity(self):
        for thresholds in (XID_THRESHOLDS, list(reversed(XID_THRESHOLDS))):
            with self.subTest(order=[t["severity"] for t in thresholds]):
                self.assertEqual(
                    severities(self.evaluate(self.database(1_900_000_000),
                                             thresholds=thresholds)),
                    ["CRITICAL"],
                )

    def test_finding_describes_the_database(self):
        finding = self.evaluate(self.database(1_600_000_000, name="orders"))[0]
        self.assertEqual(finding["subject_type"], "DATABASE")
        self.assertEqual(finding["subject_identifier"], "orders")
        self.assertEqual(finding["observed_value"], 1_600_000_000)
        self.assertEqual(finding["observed_unit"], "TRANSACTION")

    def test_each_database_is_evaluated_independently(self):
        findings = self.evaluate(
            self.database(10_000, "postgres"),
            self.database(1_600_000_000, "orders"),
            self.database(1_900_000_000, "billing"),
        )
        self.assertEqual(
            [(f["subject_identifier"], f["severity"]) for f in findings],
            [("orders", "WARNING"), ("billing", "CRITICAL")],
        )


class ReplicationSlotTests(unittest.TestCase):
    """PG-REP-001 and PG-REP-002 use rule default_severity, not thresholds."""

    STATUSES = ("reserved", "extended", "unreserved", "lost", None)

    def slots(self):
        return [
            {"snapshot_id": 1, "slot_name": f"slot_{status}", "wal_status": status}
            for status in self.STATUSES
        ]

    def test_retention_pressure_reports_only_extended(self):
        findings = engine.evaluate_replication_slot_wal_retention_pressure(
            self.slots(), rule("WARNING"), []
        )
        self.assertEqual(
            [(f["subject_identifier"], f["severity"]) for f in findings],
            [("slot_extended", "WARNING")],
        )

    def test_wal_unavailable_reports_unreserved_and_lost(self):
        findings = engine.evaluate_replication_slot_wal_unavailable(
            self.slots(), rule("CRITICAL"), []
        )
        self.assertEqual(
            [(f["subject_identifier"], f["severity"]) for f in findings],
            [("slot_unreserved", "CRITICAL"), ("slot_lost", "CRITICAL")],
        )

    def test_severity_comes_from_the_dictionary(self):
        findings = engine.evaluate_replication_slot_wal_unavailable(
            self.slots(), rule("WARNING"), []
        )
        self.assertEqual(set(severities(findings)), {"WARNING"})

    def test_finding_describes_the_slot(self):
        finding = engine.evaluate_replication_slot_wal_retention_pressure(
            self.slots(), rule("WARNING"), []
        )[0]
        self.assertEqual(finding["subject_type"], "REPLICATION_SLOT")
        self.assertIsNone(finding["observed_value"])
        self.assertEqual(finding["template_values"],
                         {"slot_name": "slot_extended", "wal_status": "extended"})


class AbortedIdleTransactionConnectionTests(unittest.TestCase):
    """PG-CONN-001"""

    def evaluate(self, count):
        row = {
            "snapshot_id": 1,
            "target_id": 1,
            "idle_in_transaction_aborted_connections": count,
        }
        return engine.evaluate_aborted_idle_transaction_connections(
            [row], rule(), ABORTED_CONNECTION_THRESHOLDS
        )

    def test_zero_connections_produces_no_finding(self):
        self.assertEqual(self.evaluate(0), [])

    def test_one_connection_is_warning(self):
        self.assertEqual(severities(self.evaluate(1)), ["WARNING"])

    def test_finding_describes_the_system(self):
        finding = self.evaluate(3)[0]
        self.assertEqual(finding["subject_type"], "SYSTEM")
        self.assertEqual(finding["subject_identifier"], "1")
        self.assertEqual(finding["observed_value"], 3)
        self.assertEqual(finding["template_values"], {"connection_count": 3})


class EvidenceFreshnessTests(unittest.TestCase):
    def requirement(self, is_required=True, max_age_seconds=600):
        return {"is_required": is_required, "max_age_seconds": max_age_seconds}

    def rows_aged(self, *ages):
        return [{"captured_at": NOW - timedelta(seconds=age)} for age in ages]

    def validate(self, rows, requirement):
        return engine.validate_evidence_freshness(rows, requirement, NOW)

    def test_fresh_evidence_is_valid(self):
        self.assertEqual(self.validate(self.rows_aged(10), self.requirement()),
                         (True, None))

    def test_evidence_exactly_at_max_age_is_valid(self):
        self.assertEqual(self.validate(self.rows_aged(600), self.requirement()),
                         (True, None))

    def test_stale_evidence_is_invalid(self):
        valid, reason = self.validate(self.rows_aged(601), self.requirement())
        self.assertFalse(valid)
        self.assertIn("stale", reason)

    def test_newest_row_decides_freshness(self):
        self.assertEqual(self.validate(self.rows_aged(5000, 10),
                                       self.requirement()),
                         (True, None))

    def test_missing_required_evidence_is_invalid(self):
        valid, reason = self.validate([], self.requirement(is_required=True))
        self.assertFalse(valid)
        self.assertIn("not available", reason)

    def test_missing_optional_evidence_is_valid(self):
        self.assertEqual(self.validate([], self.requirement(is_required=False)),
                         (True, None))

    def test_no_max_age_accepts_any_age(self):
        self.assertEqual(
            self.validate(self.rows_aged(10 ** 7),
                          self.requirement(max_age_seconds=None)),
            (True, None),
        )


DATA_DISK_THRESHOLDS = [
    threshold("WARNING", 80, "PERCENT"),
    threshold("CRITICAL", 90, "PERCENT"),
]
GB = 1024 ** 3


class DataDiskUsageTests(unittest.TestCase):
    """PG-CAP-001: the filesystem holding data_directory, per node."""

    def evidence(self, nodes):
        storage, config = [], []
        for target_id, (directory, mounts) in nodes.items():
            config.append({"target_id": target_id, "setting_name": "data_directory",
                           "setting_value": directory, "captured_at": NOW})
            config.append({"target_id": target_id, "setting_name": "port",
                           "setting_value": "5432", "captured_at": NOW})
            for i, (mount, used, total) in enumerate(mounts):
                storage.append({"snapshot_id": target_id * 10 + i, "target_id": target_id,
                                "node_name": f"node-{target_id}", "captured_at": NOW,
                                "mount_point": mount, "used_bytes": used * GB,
                                "total_bytes": total * GB, "available_bytes": (total - used) * GB})
        return {"PG_HOST_SNAPSHOT": storage, "PG_CONFIGURATION_SNAPSHOT": config}

    def evaluate(self, nodes, thresholds=DATA_DISK_THRESHOLDS):
        return engine.evaluate_data_disk_usage(self.evidence(nodes), rule(), thresholds)

    def test_below_warning_produces_no_finding(self):
        self.assertEqual(self.evaluate({1: ("/var/lib/pg", [("/", 79, 100)])}), [])

    def test_exactly_warning_is_warning(self):
        self.assertEqual(severities(self.evaluate({1: ("/var/lib/pg", [("/", 80, 100)])})),
                         ["WARNING"])

    def test_exactly_critical_is_critical(self):
        self.assertEqual(severities(self.evaluate({1: ("/var/lib/pg", [("/", 90, 100)])})),
                         ["CRITICAL"])

    def test_threshold_order_does_not_change_severity(self):
        findings = self.evaluate({1: ("/var/lib/pg", [("/", 95, 100)])},
                                 list(reversed(DATA_DISK_THRESHOLDS)))
        self.assertEqual(severities(findings), ["CRITICAL"])

    def test_only_the_data_disk_counts(self):
        # Full root disk, data on its own mount with room: no finding.
        findings = self.evaluate({1: ("/data/pg/17", [("/", 99, 100), ("/data", 10, 100),
                                                      ("/data/pg/archive", 99, 100)])})
        self.assertEqual(findings, [])

    def test_longest_matching_mount_wins_and_prefixes_are_whole_directories(self):
        findings = self.evaluate({1: ("/var/lib/pgsql/data", [("/", 10, 100),
                                                              ("/var/lib/pg", 99, 100),
                                                              ("/var/lib/pgsql", 85, 100)])})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["details"]["mount_point"], "/var/lib/pgsql")
        self.assertEqual(findings[0]["observed_value"], 85.0)

    def test_each_node_is_evaluated_independently(self):
        findings = self.evaluate({1: ("/pg", [("/", 50, 100)]),
                                  2: ("/pg", [("/", 92, 100)]),
                                  3: ("/pg", [("/", 81, 100)])})
        self.assertEqual({f["subject_identifier"]: f["severity"] for f in findings},
                         {"node-2": "CRITICAL", "node-3": "WARNING"})

    def test_node_without_data_directory_or_mount_is_skipped(self):
        evidence = self.evidence({1: ("/pg", [("/", 95, 100)])})
        evidence["PG_CONFIGURATION_SNAPSHOT"] = []
        self.assertEqual(engine.evaluate_data_disk_usage(evidence, rule(), DATA_DISK_THRESHOLDS), [])
        self.assertEqual(self.evaluate({1: ("relative/path", [("/data", 95, 100)])}), [])

    def test_root_reserved_blocks_count_as_used_like_df(self):
        # Lab postgre-1: df shows 8.7G used, 2.0G available, Use% 82; used/size alone is 77.
        evidence = self.evidence({1: ("/var/lib/postgresql/17/main", [("/", 8.7, 11.2)])})
        evidence["PG_HOST_SNAPSHOT"][0]["available_bytes"] = 2.0 * GB
        findings = engine.evaluate_data_disk_usage(evidence, rule(), DATA_DISK_THRESHOLDS)
        self.assertEqual(severities(findings), ["WARNING"])
        self.assertEqual(findings[0]["observed_value"], 81.3)

    def test_usage_without_available_falls_back_to_total(self):
        self.assertEqual(engine.usage_percent(30, None, 100), 30)
        self.assertEqual(engine.usage_percent(8, 2, 11), 80)
        self.assertIsNone(engine.usage_percent(0, None, 0))

    def test_finding_describes_node_disk_and_directory(self):
        finding = self.evaluate({1: ("/var/lib/pg/17/main", [("/", 91.5, 100)])})[0]
        self.assertEqual(finding["observed_unit"], "PERCENT")
        self.assertEqual(finding["subject_type"], "NODE")
        self.assertEqual(finding["template_values"]["used_percent"], "91.5")
        self.assertEqual(finding["details"]["data_directory"], "/var/lib/pg/17/main")
        self.assertEqual(finding["details"]["captured_at"], NOW.isoformat())
        text = ("The data disk {mount_point} on {node_name} is {used_percent}% full "
                "(data_directory {data_directory}).").format(**finding["template_values"])
        self.assertEqual(text, "The data disk / on node-1 is 91.5% full "
                               "(data_directory /var/lib/pg/17/main).")


REPLICATION_LAG_THRESHOLDS = [
    threshold("WARNING", 60, "SECOND"),
    threshold("CRITICAL", 300, "SECOND"),
]


def status_rows(replicas, sync_names=""):
    rows = [{"record_type": "SYSTEM", "snapshot_id": 1, "target_id": 1, "captured_at": NOW,
             "connected_replica_count": len(replicas), "synchronous_standby_names": sync_names}]
    for i, r in enumerate(replicas):
        row = {"record_type": "REPLICA", "snapshot_id": 10 + i, "target_id": 1, "captured_at": NOW,
               "application_name": f"pg-{i}", "client_addr": f"10.0.0.{i}", "state": "streaming",
               "sync_state": "async", "replay_lag_seconds": None, "replay_lag_bytes": 0}
        row.update(r)
        rows.append(row)
    return rows


def inventory(*nodes):
    return [{"target_id": i, "node_name": name, "captured_at": NOW, "server_address": address,
             "in_recovery": recovery} for i, (name, address, recovery) in enumerate(nodes)]


class ReplicationLagTests(unittest.TestCase):
    def evaluate(self, lag, thresholds=REPLICATION_LAG_THRESHOLDS):
        return engine.evaluate_replication_lag(
            status_rows([{"replay_lag_seconds": lag, "replay_lag_bytes": 4096}]), rule(), thresholds)

    def test_caught_up_replica_has_null_lag(self):
        self.assertEqual(self.evaluate(None), [])

    def test_boundaries(self):
        self.assertEqual(self.evaluate(59.9), [])
        self.assertEqual(severities(self.evaluate(60)), ["WARNING"])
        self.assertEqual(severities(self.evaluate(300)), ["CRITICAL"])

    def test_threshold_order_does_not_change_severity(self):
        self.assertEqual(severities(self.evaluate(400, list(reversed(REPLICATION_LAG_THRESHOLDS)))),
                         ["CRITICAL"])

    def test_finding_names_the_replica_and_wal_behind(self):
        finding = self.evaluate(75.25)[0]
        self.assertEqual(finding["subject_identifier"], "pg-0")
        self.assertEqual(finding["template_values"]["delay_note"], "")
        self.assertEqual(finding["template_values"]["lag_seconds"], "75.2")
        self.assertEqual(finding["details"]["wal_behind_bytes"], 4096)

    def lag_evidence(self, lag, delay_value=None, unit="ms"):
        evidence = {"PG_REPLICATION_STATUS": status_rows([{"replay_lag_seconds": lag}]),
                    "PG_INSTANCE_INVENTORY": inventory(("node-a", "10.0.0.0", True)),
                    "PG_CONFIGURATION_SNAPSHOT": []}
        if delay_value is not None:
            evidence["PG_CONFIGURATION_SNAPSHOT"] = [
                {"target_id": 0, "setting_name": "recovery_min_apply_delay",
                 "setting_value": str(delay_value), "unit": unit, "captured_at": NOW}]
        return evidence

    def test_intended_apply_delay_is_not_lag(self):
        # Lab 2026-10-21: recovery_min_apply_delay = 5min, replay_lag 143 s -> no finding.
        evidence = self.lag_evidence(143, 300000)
        self.assertEqual(engine.evaluate_replication_lag(evidence, rule(), REPLICATION_LAG_THRESHOLDS), [])

    def test_lag_beyond_intended_delay_is_judged(self):
        findings = engine.evaluate_replication_lag(self.lag_evidence(400, 300000), rule(),
                                                   REPLICATION_LAG_THRESHOLDS)
        self.assertEqual(severities(findings), ["WARNING"])                 # 100 s beyond
        finding = findings[0]
        self.assertEqual(finding["observed_value"], 400.0)                 # what was measured
        self.assertEqual(finding["details"]["apply_delay_seconds"], 300)
        self.assertEqual(finding["details"]["beyond_delay_seconds"], 100.0)
        text = ("Replica {replica} is {lag_seconds} seconds behind the primary in replaying "
                "changes{delay_note}.").format(**finding["template_values"])
        self.assertEqual(text, "Replica pg-0 is 400.0 seconds behind the primary in replaying "
                               "changes (100.0 seconds beyond its intended apply delay of 300 seconds).")

    def test_without_intended_delay_no_delay_note(self):
        finding = engine.evaluate_replication_lag(self.lag_evidence(75), rule(),
                                                  REPLICATION_LAG_THRESHOLDS)[0]
        self.assertEqual(finding["template_values"]["delay_note"], "")
        self.assertNotIn("apply_delay_seconds", finding["details"])

    def test_without_configuration_the_full_lag_is_judged(self):
        findings = engine.evaluate_replication_lag(self.lag_evidence(143), rule(),
                                                   REPLICATION_LAG_THRESHOLDS)
        self.assertEqual(severities(findings), ["WARNING"])

    def test_setting_units(self):
        self.assertEqual(engine.setting_seconds({"setting_value": "300000", "unit": "ms"}), 300)
        self.assertEqual(engine.setting_seconds({"setting_value": "5", "unit": "min"}), 300)
        self.assertIsNone(engine.setting_seconds({"setting_value": "on", "unit": None}))

    def test_system_row_is_not_a_replica(self):
        self.assertEqual(engine.evaluate_replication_lag(status_rows([]), rule(),
                                                         REPLICATION_LAG_THRESHOLDS), [])


class ReplicaNotStreamingTests(unittest.TestCase):
    def evaluate(self, replicas, nodes):
        return engine.evaluate_replica_not_streaming(
            {"PG_REPLICATION_STATUS": status_rows(replicas), "PG_INSTANCE_INVENTORY": nodes},
            rule("WARNING"), [])

    NODES = inventory(("node-p", "10.0.0.9", False), ("node-a", "10.0.0.0", True),
                      ("node-b", "10.0.0.1", True))

    def test_all_known_replicas_streaming(self):
        self.assertEqual(self.evaluate([{}, {}], self.NODES), [])

    def test_missing_replica_is_named(self):
        findings = self.evaluate([{}], self.NODES)
        self.assertEqual([(f["subject_identifier"], f["severity"]) for f in findings],
                         [("node-b", "WARNING")])
        self.assertEqual(findings[0]["template_values"]["state"], "not connected")

    def test_no_replica_left_is_critical(self):
        findings = self.evaluate([], self.NODES)
        self.assertEqual(severities(findings), ["CRITICAL", "CRITICAL"])

    def test_replica_not_in_streaming_state(self):
        findings = self.evaluate([{}, {"state": "catchup"}], self.NODES)
        self.assertEqual([(f["subject_identifier"], f["template_values"]["state"]) for f in findings],
                         [("pg-1", "catchup")])

    def test_standalone_server_expects_no_replica(self):
        self.assertEqual(self.evaluate([], inventory(("solo", "10.0.0.9", False))), [])

    def test_addresses_with_prefix_length_match(self):
        self.assertEqual(self.evaluate([{"client_addr": "10.0.0.0/32"}, {}], self.NODES), [])

    def test_unknown_addresses_fall_back_to_counts(self):
        nodes = inventory(("node-p", None, False), ("node-a", None, True), ("node-b", None, True))
        findings = self.evaluate([{}], nodes)
        self.assertEqual([f["subject_identifier"] for f in findings], ["1 of 2 replicas"])


class InactiveReplicationSlotTests(unittest.TestCase):
    def slot(self, name, active, temporary=False):
        return {"snapshot_id": 1, "captured_at": NOW, "slot_name": name, "slot_type": "physical",
                "database_name": None, "active": active, "temporary": temporary,
                "wal_status": "reserved"}

    def test_only_inactive_permanent_slots(self):
        findings = engine.evaluate_inactive_replication_slot(
            [self.slot("used", True), self.slot("idle", False), self.slot("tmp", False, True)],
            rule("WARNING"), [])
        self.assertEqual([(f["subject_identifier"], f["severity"]) for f in findings],
                         [("idle", "WARNING")])


class SyncStandbyMissingTests(unittest.TestCase):
    def evaluate(self, replicas, names):
        return engine.evaluate_sync_standby_missing(status_rows(replicas, names), rule("CRITICAL"), [])

    def test_asynchronous_replication_is_fine(self):
        self.assertEqual(self.evaluate([], ""), [])
        self.assertEqual(self.evaluate([], None), [])

    def test_configured_without_sync_standby_is_critical(self):
        findings = self.evaluate([{"sync_state": "async"}], "ANY 1 (*)")
        self.assertEqual(severities(findings), ["CRITICAL"])
        self.assertEqual(findings[0]["template_values"]["synchronous_standby_names"], "ANY 1 (*)")

    def test_sync_or_quorum_standby_satisfies(self):
        self.assertEqual(self.evaluate([{"sync_state": "sync"}], "*"), [])
        self.assertEqual(self.evaluate([{"sync_state": "quorum"}], "ANY 1 (*)"), [])


def settings(node_id, node_name, **values):
    return [{"target_id": node_id, "node_name": node_name, "captured_at": NOW,
             "setting_name": name, "setting_value": str(value), "unit": None,
             "source": "configuration file", "pending_restart": False}
            for name, value in values.items()]


class ConfigurationRuleTests(unittest.TestCase):
    def test_pending_restart_per_node_and_setting(self):
        rows = settings(1, "pg-1", shared_buffers="16384") + settings(2, "pg-2", shared_buffers="16384")
        rows[1]["pending_restart"] = True
        findings = engine.evaluate_pending_restart(rows, rule("WARNING"), [])
        self.assertEqual([(f["subject_identifier"], f["severity"]) for f in findings],
                         [("pg-2: shared_buffers", "WARNING")])
        self.assertEqual(findings[0]["details"]["value"], "16384")

    def test_unsafe_durability_severities(self):
        rows = settings(1, "pg-1", fsync="off", full_page_writes="off", synchronous_commit="off")
        findings = engine.evaluate_unsafe_durability(rows, rule(), [])
        self.assertEqual({f["details"]["setting"]: f["severity"] for f in findings},
                         {"fsync": "CRITICAL", "full_page_writes": "CRITICAL",
                          "synchronous_commit": "WARNING"})

    def test_safe_durability_values(self):
        rows = settings(1, "pg-1", fsync="on", full_page_writes="on", synchronous_commit="local")
        self.assertEqual(engine.evaluate_unsafe_durability(rows, rule(), []), [])

    def test_autovacuum_or_track_counts_off(self):
        rows = settings(1, "pg-1", autovacuum="off", track_counts="on") + \
            settings(2, "pg-2", autovacuum="on", track_counts="off")
        findings = engine.evaluate_autovacuum_disabled(rows, rule("CRITICAL"), [])
        self.assertEqual(sorted(f["subject_identifier"] for f in findings),
                         ["pg-1: autovacuum", "pg-2: track_counts"])


CONNECTION_THRESHOLDS = [threshold("WARNING", 80, "PERCENT"), threshold("CRITICAL", 90, "PERCENT")]


class ConnectionCapacityTests(unittest.TestCase):
    def evaluate(self, connections, max_connections=100, superuser=3, reserved=None):
        values = {"max_connections": max_connections, "superuser_reserved_connections": superuser}
        if reserved is not None:
            values["reserved_connections"] = reserved
        evidence = {
            "PG_CONNECTION_ACTIVITY": [{"snapshot_id": 1, "target_id": 9, "captured_at": NOW,
                                        "total_client_connections": connections,
                                        "active_connections": 5, "idle_connections": connections - 5,
                                        "idle_in_transaction_connections": 0}],
            "PG_CONFIGURATION_SNAPSHOT": settings(1, "pg-1", **values) + settings(2, "pg-2", max_connections=500),
            "PG_INSTANCE_INVENTORY": inventory(("pg-1", "10.0.0.1", False), ("pg-2", "10.0.0.2", True)),
        }
        evidence["PG_INSTANCE_INVENTORY"][0]["target_id"] = 1
        evidence["PG_INSTANCE_INVENTORY"][1]["target_id"] = 2
        return engine.evaluate_connection_capacity(evidence, rule(), CONNECTION_THRESHOLDS)

    def test_boundaries_against_usable_slots_of_the_primary(self):
        self.assertEqual(self.evaluate(77), [])                    # 77 / 97 = 79.4 %
        self.assertEqual(severities(self.evaluate(78)), ["WARNING"])     # 80.4 %
        self.assertEqual(severities(self.evaluate(88)), ["CRITICAL"])    # 90.7 %

    def test_reserved_connections_are_not_usable(self):
        finding = self.evaluate(80, reserved=5)[0]                 # 100 - 3 - 5 = 92
        self.assertEqual(finding["details"]["usable_connections"], 92)
        self.assertEqual(finding["details"]["reserved_connections"], 8)
        self.assertEqual(finding["observed_value"], 87.0)

    def test_finding_shows_count_and_limit(self):
        finding = self.evaluate(90)[0]
        self.assertEqual(finding["template_values"], {"connections": 90, "usable": 97, "percent": "92.8"})
        self.assertEqual(finding["details"]["max_connections"], 100)
        self.assertEqual(finding["subject_identifier"], "pg-1")


class SimpleP1RuleTests(unittest.TestCase):
    def test_mxid_boundaries(self):
        thresholds = [threshold("WARNING", 1_500_000_000, "MULTIXACT"),
                      threshold("CRITICAL", 1_800_000_000, "MULTIXACT")]
        rows = [{"snapshot_id": i, "captured_at": NOW, "database_name": f"db{i}", "mxid_age": age}
                for i, age in enumerate((1_499_999_999, 1_500_000_000, 1_800_000_000, None))]
        findings = engine.evaluate_database_mxid_wraparound(rows, rule(), thresholds)
        self.assertEqual([(f["subject_identifier"], f["severity"]) for f in findings],
                         [("db1", "WARNING"), ("db2", "CRITICAL")])
        self.assertEqual(findings[0]["observed_unit"], "MULTIXACT")

    def archiving(self, **values):
        evidence = {"PG_CONFIGURATION_SNAPSHOT": settings(1, "pg-1", **values)
                    + settings(2, "pg-2", archive_mode="off"),
                    "PG_INSTANCE_INVENTORY": inventory(("pg-1", "10.0.0.1", False),
                                                       ("pg-2", "10.0.0.2", True))}
        evidence["PG_INSTANCE_INVENTORY"][0]["target_id"] = 1
        evidence["PG_INSTANCE_INVENTORY"][1]["target_id"] = 2
        return engine.evaluate_wal_archiving(evidence, rule(), [])

    def test_archiving_judged_on_the_primary_only(self):
        self.assertEqual(self.archiving(archive_mode="on", archive_command="pgbackrest archive-push %p",
                                        archive_library=""), [])

    def test_archiving_off_is_a_warning(self):
        findings = self.archiving(archive_mode="off", archive_command="(disabled)", archive_library="")
        self.assertEqual([(f["subject_identifier"], f["severity"]) for f in findings],
                         [("pg-1: archive_mode", "WARNING")])

    def test_archiving_on_without_command_is_critical(self):
        findings = self.archiving(archive_mode="on", archive_command="", archive_library="")
        self.assertEqual(severities(findings), ["CRITICAL"])
        self.assertEqual(findings[0]["template_values"]["value"], "empty while archive_mode is on")
        self.assertEqual(findings[0]["details"]["archive_mode"], "on")

    def test_archive_library_counts_as_configured(self):
        self.assertEqual(self.archiving(archive_mode="always", archive_command="",
                                        archive_library="basic_archive"), [])

    def test_security_settings_per_node(self):
        rows = settings(1, "pg-1", ssl="off", password_encryption="md5") + \
            settings(2, "pg-2", ssl="on", password_encryption="scram-sha-256")
        ssl = engine.RULE_EVALUATORS["PG-SEC-003"](rows, rule("WARNING"), [])
        md5 = engine.RULE_EVALUATORS["PG-SEC-002"](rows, rule("WARNING"), [])
        self.assertEqual([f["subject_identifier"] for f in ssl], ["pg-1: ssl"])
        self.assertEqual([f["subject_identifier"] for f in md5], ["pg-1: password_encryption"])


class CurrentEvidenceTests(unittest.TestCase):
    REQUIREMENT = {"max_age_seconds": 600, "is_required": True}

    def test_each_row_is_judged_on_its_own_age(self):
        rows = [{"captured_at": NOW - timedelta(seconds=60)},
                {"captured_at": NOW - timedelta(seconds=601)}]
        self.assertEqual(engine.current_rows(rows, self.REQUIREMENT, NOW), rows[:1])

    def test_rows_of_targets_the_health_check_did_not_collect_are_dropped(self):
        rows = [{"target_id": 1, "captured_at": NOW}, {"target_id": 2, "captured_at": NOW}]
        self.assertEqual(engine.current_rows(rows, self.REQUIREMENT, NOW, "PG_HOST_SNAPSHOT",
                                             {(1, "PG_HOST_SNAPSHOT")}), rows[1:])
        self.assertEqual(engine.current_rows(rows, self.REQUIREMENT, NOW, "PG_HOST_SNAPSHOT",
                                             {(1, "PG_CONFIGURATION_SNAPSHOT")}), rows)

    def test_freshest_primary_wins_after_a_failover(self):
        nodes = [{"node_name": "old", "in_recovery": False, "captured_at": NOW - timedelta(hours=1)},
                 {"node_name": "new", "in_recovery": False, "captured_at": NOW},
                 {"node_name": "replica", "in_recovery": True, "captured_at": NOW}]
        self.assertEqual(engine.current_primary(nodes)["node_name"], "new")
        self.assertIsNone(engine.current_primary(nodes[2:]))


def table_row(name, live, dead=0, modified=0):
    return {"snapshot_id": 1, "target_id": 1, "captured_at": NOW, "database_name": "app",
            "schema_name": "public", "object_name": name, "is_partition": False,
            "n_live_tup": live, "n_dead_tup": dead, "n_mod_since_analyze": modified,
            "last_vacuum": None, "last_autovacuum": NOW - timedelta(days=2), "last_analyze": None,
            "last_autoanalyze": None, "autovacuum_count": 3, "autoanalyze_count": 1}


def maintenance_rule(prefix):
    keys = {"dead": ("min_dead_tuples", "large_table_dead_tuples"),
            "mod": ("min_modifications", "large_table_modifications")}[prefix]
    return {"rule_key": "PG-MAINT", "default_severity": None,
            "parameters": {keys[0]: {"value": 10000.0, "unit": "ROW"},
                           keys[1]: {"value": 50000000.0, "unit": "ROW"}}}


class MaintenanceRuleTests(unittest.TestCase):
    DEAD = [threshold("WARNING", 20, "PERCENT"), threshold("CRITICAL", 40, "PERCENT")]
    STALE = [threshold("WARNING", 20, "PERCENT"), threshold("CRITICAL", 50, "PERCENT")]

    def dead(self, *rows):
        return engine.evaluate_dead_tuple_pressure(list(rows), maintenance_rule("dead"), self.DEAD)

    def stale(self, *rows):
        return engine.evaluate_stale_statistics(list(rows), maintenance_rule("mod"), self.STALE)

    def test_small_tables_are_not_judged(self):
        self.assertEqual(self.dead(table_row("tiny", live=10, dead=9_999)), [])   # 99.9 % but small

    def test_dead_ratio_boundaries(self):
        self.assertEqual(self.dead(table_row("t", live=80_001, dead=20_000)), [])      # 19.99 %
        self.assertEqual(severities(self.dead(table_row("t", live=80_000, dead=20_000))), ["WARNING"])
        self.assertEqual(severities(self.dead(table_row("t", live=60_000, dead=40_000))), ["CRITICAL"])

    def test_large_table_warns_below_the_ratio(self):
        # 60 M dead rows in a 1 billion row table: 5.7 %, still a WARNING.
        finding = self.dead(table_row("big", live=1_000_000_000, dead=60_000_000))[0]
        self.assertEqual(finding["severity"], "WARNING")
        self.assertEqual(finding["details"]["trigger"], "large_table")
        self.assertEqual(finding["observed_value"], 5.7)
        self.assertEqual(finding["template_values"]["dead_rows"], 60_000_000)

    def test_ratio_wins_over_the_large_table_limit(self):
        finding = self.dead(table_row("big", live=60_000_000, dead=60_000_000))[0]
        self.assertEqual((finding["severity"], finding["details"]["trigger"]), ("CRITICAL", "ratio"))

    def test_stale_statistics(self):
        self.assertEqual(self.stale(table_row("t", live=100_000, modified=19_999)), [])
        self.assertEqual(severities(self.stale(table_row("t", live=100_000, modified=20_000))), ["WARNING"])
        self.assertEqual(severities(self.stale(table_row("t", live=100_000, modified=50_000))), ["CRITICAL"])
        big = self.stale(table_row("big", live=2_000_000_000, modified=60_000_000))[0]
        self.assertEqual((big["severity"], big["details"]["trigger"]), ("WARNING", "large_table"))

    def test_finding_names_the_table(self):
        finding = self.dead(table_row("orders", live=50_000, dead=50_000))[0]
        self.assertEqual(finding["subject_identifier"], "app.public.orders")
        self.assertEqual(finding["template_values"]["percent"], "50")
        self.assertEqual(finding["details"]["live_rows"], 50_000)

    def test_missing_parameter_is_a_dictionary_error(self):
        with self.assertRaises(RuntimeError):
            engine.evaluate_dead_tuple_pressure([table_row("t", 1, 20_000)],
                                                {"rule_key": "X", "parameters": {}}, self.DEAD)


def wal_row(node, in_recovery=False, archive_mode="on", failed=None, archived=None,
            timeline=126, started=None, target_id=1):
    return {"snapshot_id": target_id, "target_id": target_id, "node_name": node, "captured_at": NOW,
            "in_recovery": in_recovery, "archive_mode": archive_mode,
            "timeline_id": None if in_recovery else timeline,
            "timeline_history_file": f"{timeline:08X}.history" if started else None,
            "timeline_started_at": started, "archived_count": 10, "last_archived_wal": "0000007E00000001",
            "last_archived_time": archived, "failed_count": 3 if failed else 0,
            "last_failed_wal": "0000007E00000002" if failed else None, "last_failed_time": failed,
            "stats_reset": NOW - timedelta(days=30)}


class ArchiveFailureTests(unittest.TestCase):
    def evaluate(self, *rows):
        return engine.evaluate_archive_failures(list(rows), rule("CRITICAL"), [])

    def test_failure_after_the_last_success_is_critical(self):
        findings = self.evaluate(wal_row("pg-1", failed=NOW - timedelta(minutes=1),
                                         archived=NOW - timedelta(minutes=10)))
        self.assertEqual([(f["subject_identifier"], f["severity"]) for f in findings],
                         [("pg-1", "CRITICAL")])
        self.assertNotIn("_alt", findings[0]["template_values"])
        self.assertEqual(findings[0]["details"]["failed_count"], 3)

    def test_failure_followed_by_success_is_history(self):
        self.assertEqual(self.evaluate(wal_row("pg-1", failed=NOW - timedelta(minutes=10),
                                               archived=NOW - timedelta(minutes=1))), [])

    def test_never_succeeded_uses_the_alternative_sentence(self):
        values = self.evaluate(wal_row("pg-1", failed=NOW))[0]["template_values"]
        self.assertTrue(values["_alt"])
        self.assertEqual(values["last_archived_time"], "never")

    def test_archiving_off_is_left_to_bkp_002(self):
        self.assertEqual(self.evaluate(wal_row("pg-1", archive_mode="off", failed=NOW)), [])

    def test_replica_counts_only_with_archive_mode_always(self):
        self.assertEqual(self.evaluate(wal_row("pg-2", in_recovery=True, failed=NOW)), [])
        self.assertEqual(len(self.evaluate(wal_row("pg-2", in_recovery=True, archive_mode="always",
                                                   failed=NOW))), 1)


class PreparedTransactionTests(unittest.TestCase):
    THRESHOLDS = [threshold("WARNING", 300, "SECOND"), threshold("CRITICAL", 3600, "SECOND")]

    def evaluate(self, *ages):
        rows = [{"record_type": "SYSTEM", "snapshot_id": 1, "target_id": 1, "captured_at": NOW,
                 "max_prepared_transactions": 10, "prepared_count": len(ages)}]
        rows += [{"record_type": "TRANSACTION", "snapshot_id": 2 + i, "target_id": 1, "captured_at": NOW,
                  "transaction_id": str(1000 + i), "gid": f"tm-{i}", "prepared_at": NOW - timedelta(seconds=a),
                  "owner": "app", "database_name": "orders"} for i, a in enumerate(ages)]
        return engine.evaluate_long_prepared_transaction(rows, rule(), self.THRESHOLDS)

    def test_none_prepared_is_healthy(self):
        self.assertEqual(self.evaluate(), [])

    def test_age_boundaries(self):
        findings = self.evaluate(299, 300, 3600)
        self.assertEqual([(f["subject_identifier"], f["severity"]) for f in findings],
                         [("tm-1", "WARNING"), ("tm-2", "CRITICAL")])
        self.assertEqual((findings[1]["observed_value"], findings[1]["observed_unit"]), (3600.0, "SECOND"))
        self.assertEqual(findings[1]["template_values"],
                         {"gid": "tm-2", "database_name": "orders", "owner": "app", "age_seconds": 3600})


class RecentFailoverTests(unittest.TestCase):
    RULE = {"rule_key": "PG-HA-001", "default_severity": "WARNING",
            "parameters": {"recent_failover_window": {"value": 86400.0, "unit": "SECOND"}}}

    def evaluate(self, *rows):
        return engine.evaluate_recent_failover(list(rows), self.RULE, [])

    def test_failover_within_the_window_is_a_warning(self):
        findings = self.evaluate(wal_row("pg-3", started=NOW - timedelta(hours=3)),
                                 wal_row("pg-1", in_recovery=True, target_id=2))
        self.assertEqual([(f["subject_identifier"], f["severity"]) for f in findings], [("pg-3", "WARNING")])
        self.assertEqual(findings[0]["template_values"]["since_seconds"], 10800)
        self.assertEqual(findings[0]["template_values"]["timeline_id"], 126)
        self.assertEqual(findings[0]["observed_unit"], "SECOND")

    def test_older_failover_is_healthy(self):
        self.assertEqual(self.evaluate(wal_row("pg-3", started=NOW - timedelta(hours=25))), [])

    def test_timeline_one_never_failed_over(self):
        self.assertEqual(self.evaluate(wal_row("pg-1", timeline=1)), [])

    def test_missing_history_file_is_insufficient_evidence(self):
        with self.assertRaisesRegex(engine.InsufficientEvidence, r"\[no_timeline_history\]"):
            self.evaluate(wal_row("pg-1"))

    def test_no_primary_is_insufficient_evidence(self):
        with self.assertRaisesRegex(engine.InsufficientEvidence, r"\[no_primary\]"):
            self.evaluate(wal_row("pg-2", in_recovery=True))


if __name__ == "__main__":
    unittest.main()
