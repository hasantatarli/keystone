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


if __name__ == "__main__":
    unittest.main()
