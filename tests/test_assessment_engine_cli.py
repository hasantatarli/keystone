"""Tests for the assessment engine command-line entry point.

The CLI only selects which assessment runs against which target. These tests
check that selection without a database: the repository connection and
run_assessment() are replaced with mocks.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_assessment_engine_cli.py -v
"""

import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

from repository.intelligence import assessment_engine as engine


class AssessmentEngineCliTests(unittest.TestCase):
    def run_main(self, argv):
        conn = MagicMock(name="conn")
        connection_cm = MagicMock()
        connection_cm.__enter__.return_value = conn

        with patch.object(engine, "connect_repository",
                          return_value=connection_cm), \
                patch.object(engine, "run_assessment") as run_assessment:
            engine.main(argv)

        return conn, run_assessment

    def test_no_arguments_keeps_previous_default_behaviour(self):
        conn, run_assessment = self.run_main([])
        run_assessment.assert_called_once_with(conn, "PG_CONNECTION_HEALTH", 1)

    def test_assessment_and_target_are_passed_through(self):
        conn, run_assessment = self.run_main(
            ["--assessment", "PG_TRANSACTION_HEALTH", "--target", "7"]
        )
        run_assessment.assert_called_once_with(conn, "PG_TRANSACTION_HEALTH", 7)

    def test_target_must_be_an_integer(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as exit_info:
            engine.parse_args(["--target", "pg-cluster"])
        self.assertEqual(exit_info.exception.code, 2)

    def test_unknown_option_is_rejected(self):
        # Guards the deliberate scope: rule behaviour is not a CLI concern.
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as exit_info:
            engine.parse_args(["--threshold", "10"])
        self.assertEqual(exit_info.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
