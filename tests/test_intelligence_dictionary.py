"""Clean-install contract tests for the Engineering Intelligence Dictionary.

Why this exists
---------------
The Dictionary (assessments, rules, thresholds, evidence requirements) is
seeded by migrations. During early development some Dictionary rows were
inserted manually into the lab repository and never made it into a migration.
The lab kept working, but a clean install silently produced an incomplete
Dictionary while every migration still reported SUCCESS.

These tests install Keystone into a brand-new, disposable PostgreSQL database
and assert that the resulting Dictionary is exactly what the engine expects.
They also check that the Dictionary and the engine registries agree, so a rule
cannot exist without an evaluator (or vice versa).

Maintenance rule
----------------
EXPECTED_RULES is the explicit, reviewed contract. When a migration adds,
changes or removes a rule, update EXPECTED_RULES in the same change.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_intelligence_dictionary.py -v

PostgreSQL server binaries are required (see test_installer_findings.py):
put initdb/pg_ctl on PATH or set KEYSTONE_TEST_PG_BIN. Missing binaries skip
the database-backed tests.
"""

import contextlib
from decimal import Decimal
import io
import unittest
from unittest.mock import patch
import uuid

from psycopg import sql

from repository.install import install as installer
from repository.intelligence import assessment_engine as engine
from test_installer_findings import DisposablePostgres


# Expected Dictionary after a clean install.
#   assessment        : owning assessment_key
#   default_severity  : rule_definition.default_severity (None for threshold rules)
#   thresholds        : {severity: (threshold_value, threshold_unit)}
#   evidence          : {evidence_source: (is_required, max_age_seconds)}
EXPECTED_RULES = {
    "PG-TRAN-001": {
        "assessment": "PG_TRANSACTION_HEALTH",
        "default_severity": None,
        "thresholds": {
            "WARNING": (Decimal("300"), "SECOND"),
            "CRITICAL": (Decimal("900"), "SECOND"),
        },
        "evidence": {"PG_ACTIVITY_SNAPSHOT": (True, 600)},
    },
    "PG-TRAN-002": {
        "assessment": "PG_TRANSACTION_HEALTH",
        "default_severity": None,
        "thresholds": {
            "WARNING": (Decimal("1500000000"), "TRANSACTION"),
            "CRITICAL": (Decimal("1800000000"), "TRANSACTION"),
        },
        "evidence": {"PG_TRANSACTION_WRAPAROUND": (True, 86400)},
    },
    "PG-TRAN-003": {
        "assessment": "PG_TRANSACTION_HEALTH",
        "default_severity": None,
        "thresholds": {
            "WARNING": (Decimal("1800"), "SECOND"),
            "CRITICAL": (Decimal("3600"), "SECOND"),
        },
        "evidence": {"PG_ACTIVITY_SNAPSHOT": (True, 600)},
    },
    "PG-REP-001": {
        "assessment": "PG_REPLICATION_HEALTH",
        "default_severity": "WARNING",
        "thresholds": {},
        "evidence": {"PG_REPLICATION_SLOTS": (True, 600)},
    },
    "PG-REP-002": {
        "assessment": "PG_REPLICATION_HEALTH",
        "default_severity": "CRITICAL",
        "thresholds": {},
        "evidence": {"PG_REPLICATION_SLOTS": (True, 600)},
    },
    "PG-CONN-001": {
        "assessment": "PG_CONNECTION_HEALTH",
        "default_severity": None,
        "thresholds": {"WARNING": (Decimal("1"), "CONNECTION")},
        "evidence": {"PG_CONNECTION_ACTIVITY": (True, 600)},
    },
}

EXPECTED_ASSESSMENTS = {rule["assessment"] for rule in EXPECTED_RULES.values()}


class IntelligenceDictionaryCleanInstallTests(unittest.TestCase):
    """Install once into an empty database, then inspect the Dictionary."""

    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)

        database = "dictionary_test_" + uuid.uuid4().hex
        with cls.server.connect(autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
            )

        def connect():
            return cls.server.connect(database)

        # Run the real installer end to end; only the connection is redirected
        # to the disposable server.
        with patch.object(installer, "connect_repository", connect), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()

        cls.conn = connect()
        cls.addClassCleanup(cls.conn.close)

    def query(self, statement, params=()):
        return self.conn.execute(statement, params).fetchall()

    def installed_rules(self):
        return {
            rule_key: (assessment_key, default_severity)
            for rule_key, assessment_key, default_severity in self.query(
                """
                SELECT rd.rule_key, ad.assessment_key, rd.default_severity
                FROM keystone.rule_definition rd
                JOIN keystone.assessment_definition ad USING (assessment_id)
                WHERE rd.is_enabled AND ad.is_enabled
                """
            )
        }

    def test_clean_install_creates_expected_assessments(self):
        installed = {
            row[0] for row in self.query(
                "SELECT assessment_key FROM keystone.assessment_definition "
                "WHERE is_enabled"
            )
        }
        self.assertEqual(installed, EXPECTED_ASSESSMENTS)

    def test_clean_install_creates_expected_rules(self):
        expected = {
            key: (rule["assessment"], rule["default_severity"])
            for key, rule in EXPECTED_RULES.items()
        }
        self.assertEqual(self.installed_rules(), expected)

    def test_clean_install_creates_expected_thresholds(self):
        installed = {}
        for rule_key, severity, value, unit in self.query(
            """
            SELECT rd.rule_key, rt.severity, rt.threshold_value, rt.threshold_unit
            FROM keystone.rule_threshold rt
            JOIN keystone.rule_definition rd USING (rule_id)
            """
        ):
            installed.setdefault(rule_key, {})[severity] = (value, unit)

        expected = {
            key: rule["thresholds"]
            for key, rule in EXPECTED_RULES.items()
            if rule["thresholds"]
        }
        self.assertEqual(installed, expected)

    def test_clean_install_creates_expected_evidence_requirements(self):
        installed = {}
        for rule_key, source, is_required, max_age in self.query(
            """
            SELECT rd.rule_key, r.evidence_source, r.is_required, r.max_age_seconds
            FROM keystone.rule_evidence_requirement r
            JOIN keystone.rule_definition rd USING (rule_id)
            """
        ):
            installed.setdefault(rule_key, {})[source] = (is_required, max_age)

        expected = {key: rule["evidence"] for key, rule in EXPECTED_RULES.items()}
        self.assertEqual(installed, expected)

    def test_every_installed_rule_has_a_registered_evaluator(self):
        # The engine raises at runtime for an unregistered rule; catch it here.
        missing = set(self.installed_rules()) - set(engine.RULE_EVALUATORS)
        self.assertEqual(missing, set())

    def test_every_registered_evaluator_has_an_installed_rule(self):
        # An evaluator without a Dictionary rule is dead code or, as in the
        # original bug, a sign that the rule was never seeded on clean install.
        orphaned = set(engine.RULE_EVALUATORS) - set(self.installed_rules())
        self.assertEqual(orphaned, set())

    def test_every_evidence_requirement_has_a_registered_loader(self):
        sources = {
            row[0] for row in self.query(
                "SELECT DISTINCT evidence_source "
                "FROM keystone.rule_evidence_requirement"
            )
        }
        self.assertEqual(sources - set(engine.EVIDENCE_LOADERS), set())


class DevelopmentRepositoryUpgradeTests(unittest.TestCase):
    """V021 must be a no-op on a repository seeded the way the lab was.

    Reproduces the lab history: V001-V016, then the Transaction Health rows
    inserted manually, then the remaining migrations. Applying V021 afterwards
    must not add, duplicate or overwrite any Dictionary row.
    """

    # Deliberately different from the V021 default (300) to prove that V021
    # never overwrites values already present in an existing repository.
    TUNED_WARNING_SECONDS = Decimal("120")

    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)

    def setUp(self):
        database = "upgrade_test_" + uuid.uuid4().hex
        with self.server.connect(autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
            )
        self.database = database
        self.conn = self.server.connect(database)
        self.addCleanup(self.conn.close)

    def run_installer(self, migrations):
        def connect():
            return self.server.connect(self.database)

        with patch.object(installer, "connect_repository", connect), \
                patch.object(installer, "discover_migrations",
                             return_value=migrations), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()

    def seed_transaction_health_manually(self):
        # Mirrors the rows that were inserted by hand into the lab repository
        # on 2026-09-22, between V016 and V017.
        self.conn.execute(
            """
            INSERT INTO keystone.assessment_definition
                (assessment_key, name, provider, description)
            VALUES ('PG_TRANSACTION_HEALTH', 'Transaction Health',
                    'PostgreSQL', 'manually seeded')
            """
        )
        self.conn.execute(
            """
            INSERT INTO keystone.rule_definition
                (assessment_id, rule_key, name, evidence_source,
                 finding_template, recommendation)
            SELECT assessment_id, 'PG-TRAN-001', 'Long Idle Transaction',
                   'PG_ACTIVITY_SNAPSHOT',
                   'Session {pid} idle for {duration_seconds}s.',
                   'manually seeded'
            FROM keystone.assessment_definition
            WHERE assessment_key = 'PG_TRANSACTION_HEALTH'
            """
        )
        self.conn.execute(
            """
            INSERT INTO keystone.rule_threshold
                (rule_id, severity, threshold_value, threshold_unit)
            SELECT rule_id, t.severity, t.value, 'SECOND'
            FROM keystone.rule_definition
            CROSS JOIN (VALUES ('WARNING', %s::numeric),
                               ('CRITICAL', 900::numeric)) AS t (severity, value)
            WHERE rule_key = 'PG-TRAN-001'
            """,
            (self.TUNED_WARNING_SECONDS,),
        )
        self.conn.commit()

    def dictionary_snapshot(self):
        # Full row content, including ids, so any insert/update is detected.
        tables = (
            "assessment_definition",
            "rule_definition",
            "rule_threshold",
            "rule_evidence_requirement",
        )
        return {
            table: self.conn.execute(
                sql.SQL("SELECT * FROM keystone.{} ORDER BY 1").format(
                    sql.Identifier(table)
                )
            ).fetchall()
            for table in tables
        }

    def test_v021_is_noop_on_manually_seeded_repository(self):
        discovered = installer.discover_migrations()
        versions = [item["version"] for item in discovered]
        v016 = versions.index("V016")
        before_v021 = [item for item in discovered if item["version"] != "V021"]

        self.run_installer(discovered[: v016 + 1])
        self.seed_transaction_health_manually()
        self.run_installer(before_v021)

        before = self.dictionary_snapshot()
        self.conn.commit()

        self.run_installer(discovered)

        self.assertEqual(
            self.conn.execute(
                "SELECT status FROM keystone.migration_history "
                "WHERE version = 'V021'"
            ).fetchall(),
            [("SUCCESS",)],
        )
        self.assertEqual(self.dictionary_snapshot(), before)
        self.assertEqual(
            self.conn.execute(
                """
                SELECT rt.threshold_value
                FROM keystone.rule_threshold rt
                JOIN keystone.rule_definition rd USING (rule_id)
                WHERE rd.rule_key = 'PG-TRAN-001' AND rt.severity = 'WARNING'
                """
            ).fetchone()[0],
            self.TUNED_WARNING_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()
