"""Worker log output (ADR-0014): one summary line per task, collected rows only at DEBUG.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_worker_logging.py -v
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import unittest
from unittest.mock import MagicMock, patch

from repository.common import logging_config
from repository.worker import worker


SECRET_QUERY = "SELECT * FROM payroll WHERE ssn = '123'"


def make_task():
    return {
        "task_id": 7, "assignment_id": 3, "worker_id": "w1",
        "collector_key": "PG_ACTIVITY_SNAPSHOT", "collector_name": "Activity",
        "component": "pg", "script_file": "x.sql",
        "target_id": 1, "target_name": "lab", "provider": "PostgreSQL",
        "target_type": "SYSTEM", "host": "db", "port": 5432,
        "database_name": "postgres", "username": "keystone",
        "execution_type": "SQL", "execution_scope": "INSTANCE",
        "started_at": datetime.now(timezone.utc), "scheduled_at": None,
    }


@contextmanager
def fake_repository(collector_result=None, collector_error=None):
    """Patch every repository and target call process_task makes."""
    execute = MagicMock(return_value=collector_result, side_effect=collector_error)
    with patch.object(worker, "connect_repository", MagicMock()), \
            patch.object(worker, "connect_target", MagicMock()), \
            patch.object(worker, "execute_collector", execute), \
            patch.object(worker, "verify_task_ownership", return_value=True), \
            patch.object(worker, "persist_collector_result"), \
            patch.object(worker, "write_run_history"), \
            patch.object(worker, "remove_task", return_value=1):
        yield


class WorkerLoggingTests(unittest.TestCase):
    def run_task(self, level, **kwargs):
        with fake_repository(**kwargs), \
                self.assertLogs("keystone.worker", level=level) as logs:
            worker.process_task(make_task())
        return logs.output

    def test_success_logs_one_summary_without_rows(self):
        output = self.run_task("INFO", collector_result=[{"query_text": SECRET_QUERY}])

        self.assertEqual(len(output), 2)                    # started + finished
        self.assertIn("SUCCESS, 1 row(s)", output[1])
        self.assertNotIn(SECRET_QUERY, "\n".join(output))

    def test_rows_are_logged_only_at_debug(self):
        output = self.run_task("DEBUG", collector_result=[{"query_text": SECRET_QUERY}])
        self.assertTrue(any(SECRET_QUERY in line for line in output))

    def test_collector_failure_is_a_warning_with_status(self):
        output = self.run_task("WARNING", collector_error=RuntimeError("boom"))

        self.assertEqual(len(output), 1)
        self.assertIn("WARNING", output[0])
        self.assertIn("FAILED: boom", output[0])

    def test_username_is_not_logged(self):
        output = self.run_task("DEBUG", collector_result=[])
        self.assertNotIn("keystone", " ".join(o.split(":", 2)[2] for o in output))


class TargetConnectionTests(unittest.TestCase):
    def test_target_connection_uses_tcp_keepalive(self):
        task = make_task()
        task["auth_type"], task["credential_data"] = "PASSWORD", "x"
        with patch.object(worker, "resolve_password", return_value="secret"), \
                patch.object(worker.psycopg, "connect") as connect:
            worker.connect_target(task)

        kwargs = connect.call_args.kwargs
        self.assertEqual(kwargs["keepalives"], 1)
        self.assertEqual((kwargs["keepalives_idle"], kwargs["keepalives_interval"],
                          kwargs["keepalives_count"]), (60, 10, 6))


class LogLevelTests(unittest.TestCase):
    def tearDown(self):
        logging_config.shutdown_logging()

    def configure(self, env_level, log_dir):
        with patch.dict("os.environ", {"KEYSTONE_LOG_LEVEL": env_level}):
            return logging_config.configure_logging("test", log_dir=log_dir, console=False)

    def test_level_comes_from_environment(self):
        import tempfile
        with tempfile.TemporaryDirectory() as log_dir:
            self.assertEqual(self.configure("debug", log_dir).level, logging.DEBUG)
            logging_config.shutdown_logging()

    def test_unknown_level_falls_back_to_info(self):
        import tempfile
        with tempfile.TemporaryDirectory() as log_dir:
            self.assertEqual(self.configure("chatty", log_dir).level, logging.INFO)
            logging_config.shutdown_logging()


if __name__ == "__main__":
    unittest.main()
