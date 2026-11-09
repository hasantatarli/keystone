"""Configuration commands in the report: blocks, management type, assumptions, and applied for real.

Review 2026-11-09: the commands were only checked as text. Here the ALTER SYSTEM block
is run on a disposable PostgreSQL, reloaded and restarted, and pg_settings is compared.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_config_commands.py -v
"""

import unittest

from repository.intelligence import config_recommendations as rec
from repository.report import health_check_report as report
from test_installer_findings import DisposablePostgres

T = report.TEXTS["en"]
MB = 1024 ** 2


def row(key, value, value_type="BYTE", restart=False, assumptions=None, status="DEVIATES"):
    return {"setting_key": key, "status": status, "recommended_value": str(value),
            "value_type": value_type, "restart_required": restart, "assumptions": assumptions}


ROWS = [row("shared_buffers", 256 * MB, restart=True, assumptions=["dedicated"]),
        row("maintenance_work_mem", 128 * MB),
        row("random_page_cost", 1.1, "REAL", assumptions=["storage_type"]),
        row("checkpoint_timeout", 900, "SECOND"),
        row("wal_buffers", 16 * MB, restart=True),
        row("work_mem", 4 * MB, status="FITS")]


def profile(manager, assumed=True):
    return {"cluster_manager": {"value": manager, "assumed": False},
            "dedicated": {"value": True, "assumed": assumed},
            "storage_type": {"value": "SSD", "assumed": assumed},
            "workload_type": {"value": "OLTP", "assumed": assumed}}


def blocks(manager, rows=ROWS, cluster="pg-cluster"):
    return dict(report.command_blocks(rows, profile(manager), T, cluster))


class CommandBlockTests(unittest.TestCase):
    def test_without_patroni_reload_and_restart_are_apart(self):
        got = blocks("NONE")
        self.assertEqual(list(got), [T["config_block_reload"], T["config_block_restart"]])
        reload = got[T["config_block_reload"]].splitlines()
        self.assertIn("ALTER SYSTEM SET maintenance_work_mem = '128MB';", reload)
        self.assertIn("ALTER SYSTEM SET checkpoint_timeout = '15min';", reload)
        self.assertEqual(reload[-1], "SELECT pg_reload_conf();")
        restart = got[T["config_block_restart"]]
        self.assertIn("ALTER SYSTEM SET wal_buffers = '16MB';", restart.splitlines())
        self.assertNotIn("pg_reload_conf", restart)                 # a reload does not apply these
        self.assertNotIn("patronictl", "".join(got.values()))
        self.assertNotIn("work_mem = '4MB'", "".join(got.values()))  # fits: no command

    def test_assumed_values_are_comments(self):
        got = blocks("NONE")
        line = next(l for l in got[T["config_block_reload"]].splitlines() if "random_page_cost" in l)
        self.assertTrue(line.startswith("-- ALTER SYSTEM SET random_page_cost = '1.1';"))
        self.assertIn("storage type not given, SSD assumed", line)
        self.assertTrue(next(l for l in got[T["config_block_restart"]].splitlines()
                             if "shared_buffers" in l).startswith("-- "))

    def test_patroni_uses_patronictl_only(self):
        got = blocks("PATRONI")
        self.assertEqual(list(got), [T["config_block_patroni"], T["config_block_patroni_restart"]])
        text = got[T["config_block_patroni"]]
        self.assertNotIn("ALTER SYSTEM", "".join(got.values()))
        self.assertTrue(text.startswith("patronictl edit-config pg-cluster \\\n  --pg maintenance_work_mem=128MB"))
        self.assertIn("# patronictl edit-config pg-cluster --pg random_page_cost=1.1  # assumed:", text)
        # Patroni 4.1 requires the cluster name for restart (lab 2026-11-09).
        self.assertEqual(got[T["config_block_patroni_restart"]], "patronictl restart pg-cluster --pending")
        self.assertEqual(blocks("PATRONI", cluster=None)[T["config_block_patroni_restart"]],
                         "patronictl restart <cluster> --pending")

    def test_unknown_management_writes_every_command_as_a_comment(self):
        got = blocks(None)
        self.assertEqual(len(got), 4)
        for text in got.values():
            for line in text.splitlines():
                self.assertTrue(line.startswith(("--", "#")), line)

    def test_restart_command_only_for_settings_applied(self):
        # Only an assumed restart setting: nothing is applied, so nothing to restart.
        got = blocks("PATRONI", [row("shared_buffers", 256 * MB, restart=True, assumptions=["dedicated"])])
        self.assertNotIn(T["config_block_patroni_restart"], got)


class WindowsTests(unittest.TestCase):
    def test_windows_is_recognised_from_the_settings(self):
        setting = lambda v: {"setting_value": v}                                  # noqa: E731
        self.assertTrue(rec.on_windows({"dynamic_shared_memory_type": setting("windows")}))
        self.assertTrue(rec.on_windows({"data_directory": setting("C:/Program Files/PostgreSQL/16/data")}))
        self.assertFalse(rec.on_windows({"dynamic_shared_memory_type": setting("posix"),
                                         "data_directory": setting("/var/lib/postgresql/16/main")}))


class AppliedCommandsTests(unittest.TestCase):
    """The ALTER SYSTEM block, run as a DBA would copy it, gives the recommended values."""

    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)

    def setting(self, conn, name):
        return conn.execute("SELECT setting, unit FROM pg_settings WHERE name = %s", (name,)).fetchone()

    def test_reload_and_restart_blocks_take_effect(self):
        rows = [row("maintenance_work_mem", 128 * MB), row("checkpoint_timeout", 900, "SECOND"),
                row("random_page_cost", 1.1, "REAL"), row("shared_buffers", 256 * MB, restart=True),
                row("wal_buffers", 16 * MB, restart=True)]
        got = dict(report.command_blocks(rows, profile("NONE", assumed=False), T))
        with self.server.connect(autocommit=True) as conn:
            for title in (T["config_block_reload"], T["config_block_restart"]):
                for line in got[title].splitlines():
                    if not line.startswith("--"):
                        conn.execute(line)
            # Reload: the reload block is in effect, the restart block is pending.
            self.assertEqual(self.setting(conn, "maintenance_work_mem")[0], str(128 * 1024))
            self.assertEqual(self.setting(conn, "checkpoint_timeout")[0], "900")
            self.assertEqual(self.setting(conn, "random_page_cost")[0], "1.1")
            pending = {r[0] for r in conn.execute("SELECT name FROM pg_settings WHERE pending_restart")}
            self.assertIn("shared_buffers", pending)
            self.assertNotEqual(self.setting(conn, "shared_buffers")[0], str(256 * 1024 // 8))
        self.server.command([self.server.pg_ctl, "-D", str(self.server.data), "-l", str(self.server.log),
                             "-w", "-t", "30", "restart"])
        with self.server.connect(autocommit=True) as conn:
            self.assertEqual(self.setting(conn, "shared_buffers")[0], str(256 * 1024 // 8))   # 8kB pages
            self.assertEqual(self.setting(conn, "wal_buffers")[0], str(16 * 1024 // 8))
            conn.execute("ALTER SYSTEM RESET ALL")


if __name__ == "__main__":
    unittest.main()
