"""Tests for shared technical logging (ADR-0014).

Covers the rotating log file, the keystone.event_log repository handler
(significance filter, context, exceptions, independence from the caller's
transaction, behaviour when the repository is unavailable) and the
assessment engine's use of it.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_logging.py -v

PostgreSQL server binaries are required (see test_installer_findings.py).
"""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import logging
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid
from pathlib import Path

from psycopg import sql
from psycopg.rows import dict_row

from repository.common import logging_config
from repository.common.logging_config import configure_logging, get_logger
from repository.install import install as installer
from repository.intelligence import assessment_engine as engine
from test_installer_findings import DisposablePostgres


class LoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)

        cls.database = "logging_test_" + uuid.uuid4().hex
        with cls.server.connect(autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database))
            )

        # The installer expects tuple rows; give it a plain connection.
        def connect_plain():
            return cls.server.connect(cls.database)

        with patch.object(installer, "connect_repository", connect_plain), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()

    @classmethod
    def connect(cls):
        return cls.server.connect(cls.database, row_factory=dict_row)

    def setUp(self):
        self.log_dir = tempfile.mkdtemp(prefix="keystone-logs-")
        self.addCleanup(shutil.rmtree, self.log_dir, True)
        self.addCleanup(logging_config.shutdown_logging)
        with self.connect() as conn:
            conn.execute("TRUNCATE keystone.event_log")

    def configure(self, connect=None):
        return configure_logging(
            "test_component",
            connect=connect,
            log_dir=self.log_dir,
            console=False,
        )

    def events(self):
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM keystone.event_log ORDER BY event_id"
            ).fetchall()

    def log_file(self):
        return (Path(self.log_dir) / "test_component.log").read_text(encoding="utf-8")

    # ---------------------------------------------------------------- file

    def test_file_receives_every_level_with_timestamp_and_level(self):
        self.configure()
        logger = get_logger("unit")

        logger.info("info message")
        logger.warning("warning message")

        content = self.log_file()
        self.assertIn("INFO", content)
        self.assertIn("info message", content)
        self.assertIn("WARNING", content)
        self.assertIn("keystone.unit", content)
        # Timestamp at the start of each line, e.g. 2026-10-14 12:00:00,123
        self.assertRegex(content.splitlines()[0], r"^\d{4}-\d{2}-\d{2} ")

    def test_configure_twice_does_not_duplicate_handlers(self):
        self.configure(connect=self.connect)
        root = self.configure(connect=self.connect)

        self.assertEqual(len(root.handlers), 2)  # file + repository
        get_logger("unit").warning("once")
        self.assertEqual(len(self.events()), 1)

    # ---------------------------------------------------------- event_log

    def test_only_significant_records_reach_event_log(self):
        self.configure(connect=self.connect)
        logger = get_logger("unit")

        logger.info("routine information")
        logger.warning("something needs attention")
        logger.info("worker started", extra={"keystone_event": True})

        events = self.events()
        self.assertEqual(
            [(e["level"], e["message"]) for e in events],
            [("WARNING", "something needs attention"),
             ("INFO", "worker started")],
        )
        self.assertEqual(events[0]["component"], "test_component")
        self.assertEqual(events[0]["logger_name"], "keystone.unit")
        self.assertIsNotNone(events[0]["process_id"])
        self.assertIsNotNone(events[0]["hostname"])

    def test_context_and_exception_are_stored(self):
        self.configure(connect=self.connect)

        try:
            raise ValueError("bad value")
        except ValueError:
            get_logger("unit").error(
                "rule failed",
                exc_info=True,
                extra={"context": {"assessment_run_id": 7, "rule_key": "PG-X"}},
            )

        event = self.events()[0]
        self.assertEqual(event["context"], {"assessment_run_id": 7, "rule_key": "PG-X"})
        self.assertIn("ValueError: bad value", event["exception"])
        self.assertIn("Traceback", event["exception"])

    def test_event_survives_rollback_of_the_failed_work(self):
        self.configure(connect=self.connect)

        work = self.connect()
        self.addCleanup(work.close)
        work.execute("SELECT 1")  # open a transaction on the work connection
        get_logger("unit").error("work failed")
        work.rollback()

        self.assertEqual([e["message"] for e in self.events()], ["work failed"])

    def test_unreachable_repository_does_not_break_the_application(self):
        def unreachable():
            raise ConnectionError("repository down")

        self.configure(connect=unreachable)

        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            get_logger("unit").error("first failure")
            get_logger("unit").error("second failure")

        # Still in the file; reported once on stderr; no exception raised.
        content = self.log_file()
        self.assertIn("first failure", content)
        self.assertIn("second failure", content)
        self.assertEqual(stderr.getvalue().count("could not write"), 1)

    def test_handler_reconnects_after_a_failure(self):
        attempts = []

        def flaky_connect():
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("temporarily down")
            return self.connect()

        self.configure(connect=flaky_connect)

        with contextlib.redirect_stderr(io.StringIO()):
            get_logger("unit").error("lost")
            get_logger("unit").error("recorded")

        self.assertEqual([e["message"] for e in self.events()], ["recorded"])

    # -------------------------------------------------------------- engine

    def test_engine_rule_error_is_logged_with_traceback_and_context(self):
        self.configure(connect=self.connect)

        with self.connect() as conn:
            target_id = conn.execute(
                "INSERT INTO keystone.target (name, provider, target_type, environment) "
                "VALUES ('log-target', 'PostgreSQL', 'SYSTEM', 'TEST') "
                "RETURNING target_id"
            ).fetchone()["target_id"]
            conn.execute(
                "INSERT INTO postgresql.activity_snapshot "
                "(target_id, captured_at, pid, state, backend_type) "
                "VALUES (%s, now(), 1, 'active', 'client backend')",
                (target_id,),
            )

        def broken(rows, rule, thresholds):
            raise ValueError("evaluator bug")

        with patch.dict(engine.RULE_EVALUATORS, {"PG-TRAN-001": broken}), \
                self.connect() as conn:
            run_id = engine.run_assessment(conn, "PG_TRANSACTION_HEALTH", target_id)

        warnings = [e for e in self.events() if e["level"] == "WARNING"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("PG-TRAN-001", warnings[0]["message"])
        self.assertIn("evaluator bug", warnings[0]["exception"])
        self.assertEqual(warnings[0]["context"],
                         {"assessment_run_id": run_id, "rule_key": "PG-TRAN-001"})
        self.assertIn("Rule PG-TRAN-001 ended with ERROR", self.log_file())


if __name__ == "__main__":
    unittest.main()
