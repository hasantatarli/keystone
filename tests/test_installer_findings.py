"""Regression tests for installer ordering and exactly-once migration iteration.

Ordering/iteration tests assert correct behaviour. PG005 tests still document
the unfixed, data-dependent upgrade failure and its empty-table control.

Run from the repository root (requires the declared psycopg dependency):
    python -B -m unittest discover -s tests -p test_installer_findings.py -v

Integration tests start a disposable, loopback-only PostgreSQL cluster and never
use KEYSTONE_REPOSITORY_* or an existing server. Put initdb and pg_ctl on PATH,
or set KEYSTONE_TEST_PG_BIN to their directory. Missing server binaries cause
an explicit skip; a server startup failure is an error, not a skip.
"""

import contextlib
import io
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid
import locale

import psycopg
from psycopg import sql

from repository.install import install as installer


def migration(version):
    return next(
        item for item in installer.discover_migrations()
        if item["version"] == version
    )


class InstallerControlFlowTests(unittest.TestCase):
    def test_discovery_places_all_core_migrations_before_providers(self):
        discovered = installer.discover_migrations()
        core = [item for item in discovered if item["component"] == "Repository.Core"]
        providers = [item for item in discovered if item["component"] != "Repository.Core"]
        self.assertTrue(core)
        self.assertTrue(providers)
        self.assertEqual(discovered, core + providers)
        for component in {item["component"] for item in discovered}:
            numbers = [item["migration_no"] for item in discovered
                       if item["component"] == component]
            self.assertEqual(numbers, sorted(numbers))

    def test_core_priority_is_independent_of_source_order_and_provider_name(self):
        core, postgres = installer.MIGRATION_SOURCES
        # Reuse real provider files under an alphabetically earlier component.
        # Discovery should prioritize Core regardless of the input order.
        earlier_provider = {**postgres, "component": "AAA.Telemetry"}
        with patch.object(installer, "MIGRATION_SOURCES",
                          [postgres, earlier_provider, core]):
            discovered = installer.discover_migrations()
        order = list(dict.fromkeys(item["component"] for item in discovered))
        self.assertEqual(order, ["Repository.Core", "AAA.Telemetry", "PostgreSQL.Telemetry"])

    def run_main_with_successful_executor(self, pending):
        """Keep the real main/get_pending logic; replace only I/O/execution."""
        connection = object()
        with (
            patch.object(installer, "connect_repository",
                         return_value=contextlib.nullcontext(connection)),
            patch.object(installer, "run_bootstrap"),
            patch.object(installer, "get_successful_migrations", return_value=[]),
            patch.object(installer, "discover_migrations", return_value=pending),
            patch.object(installer, "execute_migration", return_value=True) as execute,
            patch.object(installer, "register_collectors"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            installer.main()
        return [call.args[1]["version"] for call in execute.call_args_list]

    def test_two_pending_migrations_are_each_executed_once(self):
        pending = [migration("V001"), migration("V002")]
        self.assertEqual(
            self.run_main_with_successful_executor(pending),
            ["V001", "V002"],
        )

    def test_single_pending_migration_is_executed_once_control(self):
        self.assertEqual(
            self.run_main_with_successful_executor([migration("V001")]),
            ["V001"],
        )

    def test_no_pending_migrations_execute_nothing(self):
        self.assertEqual(self.run_main_with_successful_executor([]), [])

    def test_failure_stops_before_later_migrations_and_registration(self):
        pending = [migration(version) for version in ("V001", "V002", "V003")]
        with (
            patch.object(installer, "connect_repository",
                         return_value=contextlib.nullcontext(object())),
            patch.object(installer, "run_bootstrap"),
            patch.object(installer, "get_successful_migrations", return_value=[]),
            patch.object(installer, "discover_migrations", return_value=pending),
            patch.object(installer, "execute_migration", side_effect=[True, False]) as execute,
            patch.object(installer, "register_collectors") as register,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as failure:
                installer.main()
        self.assertEqual(failure.exception.code, 1)
        self.assertEqual([call.args[1]["version"] for call in execute.call_args_list],
                         ["V001", "V002"])
        register.assert_not_called()


class DisposablePostgres:
    """Own all server state; never accept a DSN pointing at an existing DB."""

    def __init__(self):
        bin_dir = os.environ.get("KEYSTONE_TEST_PG_BIN")
        suffix = ".exe" if os.name == "nt" else ""
        self.initdb = (
            str(Path(bin_dir) / ("initdb" + suffix))
            if bin_dir else shutil.which("initdb")
        )
        self.pg_ctl = (
            str(Path(bin_dir) / ("pg_ctl" + suffix))
            if bin_dir else shutil.which("pg_ctl")
        )
        if not all(path and Path(path).is_file()
                   for path in (self.initdb, self.pg_ctl)):
            raise unittest.SkipTest(
                "PostgreSQL initdb/pg_ctl required: set KEYSTONE_TEST_PG_BIN."
            )
        self.temp = None
        self.may_be_running = False

    def command(self, args, timeout=60):
        # A server child can inherit pipe handles on Windows. Use a file so
        # waiting for pg_ctl does not also wait for the server to close stdout.
        # Explicit argv, no shell or visible Windows helper window.
        with (self.root / "commands.log").open("a+b") as output:
            output.seek(0, os.SEEK_END)
            start = output.tell()

            result = subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            output.seek(start)
            diagnostics = output.read().decode(
                locale.getpreferredencoding(False),
                errors="replace",
            )

        if result.returncode:
            raise RuntimeError(
                f"{Path(args[0]).name} exited {result.returncode}\n"
                f"{diagnostics}"
            )

        return result

    def start(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keystone-installer-tests-")
        self.root = Path(self.temp.name).resolve()
        self.data = self.root / "data"
        self.log = self.root / "server.log"
        try:
            self.command([
                self.initdb, "-D", str(self.data), "-U", "keystone_test",
                "--auth=trust", "--encoding=UTF8", "--no-locale",
            ])
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                self.port = listener.getsockname()[1]
            # Avoid pg_ctl's platform-dependent quoting of empty -c values.
            with (self.data / "postgresql.conf").open("a", encoding="utf-8") as config:
                config.write(
                    f"\nlisten_addresses = '127.0.0.1'\nport = {self.port}\n"
                    "unix_socket_directories = ''\n"
                )
            self.may_be_running = True
            self.command([
                self.pg_ctl, "-D", str(self.data), "-l", str(self.log),
                "-w", "-t", "30", "start",
            ])
        except Exception as exc:
            log = self.log.read_text(encoding="utf-8", errors="replace") \
                if self.log.exists() else ""
            self.close()
            raise RuntimeError(f"Disposable PostgreSQL startup failed: {exc}\n{log}") from exc

    def connect(self, dbname="postgres", **kwargs):
        return psycopg.connect(
            host="127.0.0.1", port=self.port, user="keystone_test",
            password="", dbname=dbname, connect_timeout=5,
            options="-c statement_timeout=10000 -c lock_timeout=5000",
            **kwargs,
        )

    def close(self):
        if self.temp is None:
            return
        # Never remove data files while the disposable server is running.
        if self.may_be_running and (self.data / "postmaster.pid").exists():
            self.command([
                self.pg_ctl, "-D", str(self.data), "-m", "fast",
                "-w", "-t", "30", "stop",
            ])
        self.may_be_running = False
        # TemporaryDirectory owns exactly this newly generated absolute path.
        if self.root.parent != Path(tempfile.gettempdir()).resolve() \
                or not self.root.name.startswith("keystone-installer-tests-"):
            raise RuntimeError(f"Refusing cleanup outside test temp root: {self.root}")
        self.temp.cleanup()
        self.temp = None


class InstallerPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)

    def setUp(self):
        self.database = "installer_test_" + uuid.uuid4().hex
        with self.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database)))
        self.conn = self.connect()
        self.addCleanup(self.conn.close)

    def connect(self):
        return self.server.connect(self.database)

    def history(self):
        return self.conn.execute(
            "SELECT version, status FROM keystone.migration_history "
            "ORDER BY execution_id"
        ).fetchall()

    def run_main(self, selected=None):
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(installer, "connect_repository", self.connect))
            if selected is not None:
                # Focused loop test uses the real first two core migrations.
                stack.enter_context(patch.object(
                    installer, "discover_migrations", return_value=selected
                ))
                # V002 is too early to register current collector metadata.
                stack.enter_context(patch.object(installer, "register_collectors"))
            stack.enter_context(contextlib.redirect_stdout(output))
            installer.main()
        return output.getvalue()

    def assert_complete_install(self):
        discovered = installer.discover_migrations()
        self.assertEqual(self.history(), [
            (item["version"], "SUCCESS") for item in discovered
        ])
        actual_collectors = self.conn.execute(
            "SELECT collector_key, checksum, execution_scope, execution_type "
            "FROM keystone.collector_definition ORDER BY collector_key"
        ).fetchall()
        expected_collectors = sorted(
            (item["collector_key"], item["checksum"], item["execution_scope"],
             item["execution_type"]) for item in installer.discover_collectors()
        )
        self.assertEqual(actual_collectors, expected_collectors)
        for component in {item["component"] for item in discovered}:
            latest = max((item for item in discovered if item["component"] == component),
                         key=lambda item: item["migration_no"])
            self.assertEqual(self.conn.execute(
                "SELECT value FROM keystone.control WHERE name = %s",
                (f"{component}.CurrentMigration",),
            ).fetchone()[0], latest["version"])

    def test_clean_install_applies_all_real_migrations_once_and_registers_collectors(self):
        output = self.run_main()
        self.assertIn("Installer completed successfully.", output)
        self.assert_complete_install()

    def test_second_full_install_does_not_reexecute_migrations_or_duplicate_collectors(self):
        self.run_main()
        self.assert_complete_install()
        history_before = self.conn.execute(
            "SELECT execution_id, component, version, status, checksum "
            "FROM keystone.migration_history ORDER BY execution_id"
        ).fetchall()
        collectors_before = self.conn.execute(
            "SELECT collector_id, collector_key FROM keystone.collector_definition "
            "ORDER BY collector_id"
        ).fetchall()
        self.conn.commit()
        output = self.run_main()
        self.assertIn("No pending migrations.", output)
        self.assert_complete_install()
        self.assertEqual(self.conn.execute(
            "SELECT execution_id, component, version, status, checksum "
            "FROM keystone.migration_history ORDER BY execution_id"
        ).fetchall(), history_before)
        self.assertEqual(self.conn.execute(
            "SELECT collector_id, collector_key FROM keystone.collector_definition "
            "ORDER BY collector_id"
        ).fetchall(), collectors_before)

    def test_two_real_pending_migrations_each_have_one_success_record(self):
        output = self.run_main([migration("V001"), migration("V002")])
        self.assertEqual(self.history(), [
            ("V001", "SUCCESS"), ("V002", "SUCCESS"),
        ])
        self.assertIn("Installer completed successfully.", output)
        self.assertEqual(self.conn.execute(
            "SELECT value FROM keystone.control "
            "WHERE name = 'Repository.Core.CurrentMigration'"
        ).fetchone()[0], "V002")

    def prepare_pg004(self, populated):
        # Apply the actual prerequisite files in dependency order to isolate PG005.
        with contextlib.redirect_stdout(io.StringIO()):
            installer.run_bootstrap(self.conn)
            for version in ("V001", "PG001", "PG002", "PG003", "PG004"):
                self.assertTrue(installer.execute_migration(self.conn, migration(version)))
        if populated:
            target_id = self.conn.execute(
                "INSERT INTO keystone.target (name, provider, target_type, environment) "
                "VALUES ('test', 'PostgreSQL', 'SYSTEM', 'TEST') RETURNING target_id"
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO postgresql.table_capacity_snapshot "
                "(target_id, captured_at, database_oid, database_name, schema_name, "
                "table_oid, table_name, is_partitioned, partition_count, "
                "table_size_bytes, indexes_size_bytes, toast_size_bytes, "
                "total_size_bytes, estimated_rows, index_count) "
                "VALUES (%s, '2026-01-01T00:00:00Z', 16384, 'app', 'public', "
                "16385, 'orders', FALSE, 0, 8192, 0, 0, 8192, 1, 0)",
                (target_id,),
            )
            self.conn.commit()

    def columns(self):
        return {
            name for (name,) in self.conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'postgresql' AND table_name = 'table_capacity_snapshot'"
            ).fetchall()
        }

    def test_pg005_succeeds_on_empty_pg004_table_control(self):
        self.prepare_pg004(populated=False)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(installer.execute_migration(self.conn, migration("PG005")))
        columns = self.columns()
        self.assertTrue({"object_oid", "object_name", "object_type"} <= columns)
        self.assertTrue({"table_oid", "table_name"}.isdisjoint(columns))
        self.assertEqual(self.history()[-1], ("PG005", "SUCCESS"))

    def test_pg005_fails_on_populated_pg004_and_installer_rolls_back(self):
        self.prepare_pg004(populated=True)
        pg005 = migration("PG005")
        # First prove the actual PostgreSQL error type, without emulating SQL.
        with self.assertRaises(psycopg.errors.NotNullViolation) as failure:
            self.conn.execute(pg005["path"].read_text(encoding="utf-8"))
        self.assertEqual(failure.exception.sqlstate, "23502")
        self.assertEqual(failure.exception.diag.column_name, "object_type")
        self.conn.rollback()
        # Then prove how the unchanged installer handles the same upgrade.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(installer.execute_migration(self.conn, pg005))
        self.assertEqual(self.history()[-1], ("PG005", "FAILED"))
        error = self.conn.execute(
            "SELECT error_message FROM keystone.migration_history WHERE version = 'PG005'"
        ).fetchone()[0]
        self.assertIn('column "object_type"', error)
        self.assertIn("contains null values", error)
        columns = self.columns()
        self.assertTrue({"table_oid", "table_name"} <= columns)
        self.assertTrue({"object_oid", "object_name", "object_type"}.isdisjoint(columns))
        self.assertEqual(self.conn.execute(
            "SELECT table_oid, table_name, table_size_bytes "
            "FROM postgresql.table_capacity_snapshot"
        ).fetchall(), [(16385, "orders", 8192)])
        self.assertEqual(self.conn.execute(
            "SELECT value FROM keystone.control "
            "WHERE name = 'PostgreSQL.Telemetry.CurrentMigration'"
        ).fetchone()[0], "PG004")


if __name__ == "__main__":
    unittest.main()
