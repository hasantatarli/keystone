"""Target command: define systems without SQL (V069, Installation Guide step 6).

The disposable server is both the repository and the server being added
(trust authentication: any password connects).

Run from the repository root:
    python -B -m unittest discover -s tests -p test_target_cli.py -v
"""

import contextlib
import io
import os
import socket
import unittest
from unittest.mock import patch
import uuid

from cryptography.fernet import Fernet
from psycopg import errors, sql
from psycopg.rows import dict_row

from repository.common.credentials import decrypt_credential
from repository.install import install as installer
from repository.tools import target
from test_installer_findings import DisposablePostgres


def closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TargetCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)
        cls.template = "target_cli_template_" + uuid.uuid4().hex
        with cls.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.template)))
        with patch.object(installer, "connect_repository", lambda: cls.server.connect(cls.template)), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()

    def setUp(self):
        self.database = "target_cli_" + uuid.uuid4().hex
        with self.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(self.database), sql.Identifier(self.template)))
        self.conn = self.connect()
        self.addCleanup(self.conn.close)
        env = patch.dict(os.environ, {"KEYSTONE_MASTER_KEY": Fernet.generate_key().decode()})
        env.start()
        self.addCleanup(env.stop)
        self.password = "s3cret-pw"

    def connect(self):
        return self.server.connect(self.database, row_factory=dict_row)

    def run_cmd(self, *argv, password=None):
        out = io.StringIO()
        with patch.object(target.getpass, "getpass", return_value=password or self.password), \
                contextlib.redirect_stdout(out):
            target.main(list(argv), connect=self.connect)
        return out.getvalue()

    def server_args(self, port=None):
        return ["--host", "127.0.0.1", "--port", str(port or self.server.port), "--user", "keystone_test"]

    def targets(self):
        return self.conn.execute(
            "SELECT target_id, name, target_type, topology, parent_target_id, environment "
            "FROM keystone.target ORDER BY target_id").fetchall()

    def connections(self):
        return self.conn.execute(
            "SELECT target_id, host, port, database_name, username, credential_data "
            "FROM keystone.target_connection ORDER BY connection_id").fetchall()

    # ------------------------------------------------------------------ add-server

    def test_add_server_is_one_entry_with_a_hidden_server(self):
        out = self.run_cmd("add-server", "--name", "laptop-pg", "--environment", "lab", *self.server_args())
        self.assertIn("Connected: PostgreSQL", out)
        self.assertIn("primary", out)
        system, server = self.targets()
        self.assertEqual((system["target_type"], system["topology"], system["environment"]),
                         ("SYSTEM", "STANDALONE", "LAB"))
        self.assertEqual((server["target_type"], server["parent_target_id"], server["topology"]),
                         ("NODE", system["target_id"], None))
        connections = self.connections()
        self.assertEqual([c["target_id"] for c in connections], [system["target_id"], server["target_id"]])
        for c in connections:
            self.assertTrue(c["credential_data"].startswith("gAAAAA"))
            self.assertEqual(decrypt_credential(c["credential_data"]), self.password)
        self.assertIn(f"--target {system['target_id']}", out)

        listed = self.run_cmd("list")
        self.assertEqual(listed.count("laptop-pg"), 1)
        self.assertIn("single server", listed)
        self.assertNotIn(self.password, listed)
        self.assertNotIn("gAAAAA", listed)

    def test_unreachable_server_writes_nothing(self):
        with self.assertRaises(target.TargetError) as raised:
            self.run_cmd("add-server", "--name", "x", "--environment", "LAB", *self.server_args(closed_port()))
        self.assertIn("Nothing was written", str(raised.exception))
        self.assertIn("pg_hba.conf", str(raised.exception))
        self.assertEqual(self.targets(), [])

    def test_skip_connection_test_stores_without_trying(self):
        out = self.run_cmd("add-server", "--name", "remote", "--environment", "PROD",
                           *self.server_args(closed_port()), "--skip-connection-test")
        self.assertIn("not tested", out)
        self.assertEqual(len(self.targets()), 2)

    def test_missing_information_stops_before_anything(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.run_cmd("add-server", "--name", "x", "--host", "127.0.0.1", "--user", "u")
        self.assertEqual(raised.exception.code, 2)          # argparse: --environment is required
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cmd("add-member", "--name", "x", "--host", "h", "--user", "u")   # no --cluster
        self.assertEqual(self.targets(), [])

    def test_no_master_key_writes_nothing(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(target.TargetError) as raised:
            self.run_cmd("add-server", "--name", "x", "--environment", "LAB", *self.server_args())
        self.assertIn("KEYSTONE_MASTER_KEY", str(raised.exception))
        self.assertEqual(self.targets(), [])

    def test_empty_password_writes_nothing(self):
        with self.assertRaises(target.TargetError):
            with patch.object(target.getpass, "getpass", return_value=""), \
                    contextlib.redirect_stdout(io.StringIO()):
                target.main(["add-server", "--name", "x", "--environment", "LAB", *self.server_args()],
                            connect=self.connect)
        self.assertEqual(self.targets(), [])

    def test_names_and_addresses_are_not_defined_twice(self):
        self.run_cmd("add-server", "--name", "pg-a", "--environment", "LAB", *self.server_args())
        with self.assertRaises(target.TargetError) as raised:
            self.run_cmd("add-server", "--name", "PG-A", "--environment", "LAB",
                         *self.server_args(), "--skip-connection-test")
        self.assertIn("A system named pg-a already exists", str(raised.exception))   # the stored name
        with self.assertRaises(target.TargetError) as raised:
            self.run_cmd("add-server", "--name", "pg-b", "--environment", "LAB", *self.server_args())
        self.assertIn("already defined", str(raised.exception))
        self.assertEqual(len(self.targets()), 2)

    # ------------------------------------------------------------------ clusters

    def test_cluster_with_members_by_name_and_id(self):
        self.run_cmd("add-cluster", "--name", "pg-prod", "--environment", "PROD",
                     "--host", "vip.example", "--user", "keystone_test", "--skip-connection-test")
        cluster = self.targets()[0]
        self.assertEqual((cluster["target_type"], cluster["topology"]), ("SYSTEM", "CLUSTER"))
        out = self.run_cmd("add-member", "--cluster", "PG-PROD", "--name", "postgre-1", *self.server_args())
        self.assertIn("Added postgre-1 to cluster pg-prod", out)
        self.run_cmd("add-member", "--cluster", str(cluster["target_id"]), "--name", "postgre-2",
                     "--host", "10.9.9.2", "--user", "keystone_test", "--skip-connection-test")
        members = [t for t in self.targets() if t["parent_target_id"] == cluster["target_id"]]
        self.assertEqual([(m["name"], m["target_type"], m["environment"]) for m in members],
                         [("postgre-1", "NODE", "PROD"), ("postgre-2", "NODE", "PROD")])
        self.assertEqual(len(self.connections()), 3)
        with self.assertRaises(target.TargetError) as raised:
            self.run_cmd("add-member", "--cluster", "pg-prod", "--name", "POSTGRE-1",
                         "--host", "10.9.9.3", "--user", "u", "--skip-connection-test")
        self.assertIn("already has a member named postgre-1", str(raised.exception))

        listed = self.run_cmd("list")
        self.assertIn("cluster", listed)
        self.assertIn("member of pg-prod", listed)

    def test_member_only_goes_to_a_cluster(self):
        self.run_cmd("add-server", "--name", "laptop-pg", "--environment", "LAB", *self.server_args())
        with self.assertRaises(target.TargetError) as raised:
            self.run_cmd("add-member", "--cluster", "laptop-pg", "--name", "x",
                         "--host", "10.9.9.9", "--user", "u", "--skip-connection-test")
        self.assertIn("single server", str(raised.exception))
        with self.assertRaises(target.TargetError) as raised:
            self.run_cmd("add-member", "--cluster", "nope", "--name", "x",
                         "--host", "10.9.9.9", "--user", "u", "--skip-connection-test")
        self.assertIn("There is no system named nope", str(raised.exception))
        self.assertIn("laptop-pg", str(raised.exception))           # the names to choose from
        self.assertEqual(len(self.targets()), 2)

    # ------------------------------------------------------------------ set-password

    def test_set_password_changes_every_connection_of_the_system(self):
        self.run_cmd("add-server", "--name", "laptop-pg", "--environment", "LAB", *self.server_args())
        out = self.run_cmd("set-password", "--name", "LAPTOP-PG", password="new-pw")
        self.assertIn("2 connection(s)", out)
        self.assertEqual({decrypt_credential(c["credential_data"]) for c in self.connections()}, {"new-pw"})

    def test_set_password_tries_before_writing_and_asks_which_user(self):
        self.run_cmd("add-cluster", "--name", "c", "--environment", "LAB", "--host", "10.9.9.1",
                     "--user", "mon_a", "--skip-connection-test")
        self.run_cmd("add-member", "--cluster", "c", "--name", "m", "--host", "10.9.9.2",
                     "--user", "mon_b", "--skip-connection-test")
        with self.assertRaises(target.TargetError) as raised:
            self.run_cmd("set-password", "--name", "c", password="x")
        self.assertIn("--user", str(raised.exception))
        before = [c["credential_data"] for c in self.connections()]
        with self.assertRaises(target.TargetError):                    # 10.9.9.1 does not answer
            with patch.object(target, "try_connection", side_effect=target.TargetError("no")):
                self.run_cmd("set-password", "--name", "c", "--user", "mon_a", password="x")
        self.assertEqual([c["credential_data"] for c in self.connections()], before)
        self.run_cmd("set-password", "--name", "c", "--user", "mon_a", "--skip-connection-test", password="x")
        after = self.connections()
        self.assertEqual(decrypt_credential(after[0]["credential_data"]), "x")
        self.assertEqual(after[1]["credential_data"], before[1])

    # ------------------------------------------------------------------ V069

    def test_active_top_level_names_are_unique_inactive_ones_not(self):
        add = ("INSERT INTO keystone.target (name, provider, target_type, environment, is_active) "
               "VALUES (%s, 'PostgreSQL', %s, 'LAB', %s)")
        self.conn.execute(add, ("old", "SYSTEM", False))
        self.conn.execute(add, ("old", "SYSTEM", True))
        self.conn.execute(add, ("lone", "NODE", True))
        self.conn.commit()
        with self.assertRaises(errors.UniqueViolation):
            self.conn.execute(add, ("LONE", "SYSTEM", True))
        self.conn.rollback()
        with self.assertRaises(errors.CheckViolation):
            self.conn.execute("INSERT INTO keystone.target (name, provider, target_type, environment, "
                              "topology) VALUES ('n', 'PostgreSQL', 'NODE', 'LAB', 'CLUSTER')")
        self.conn.rollback()


class TopologyBackfillTests(unittest.TestCase):
    """V069 on a repository that already has targets."""

    def test_existing_systems_get_their_topology(self):
        server = DisposablePostgres()
        server.start()
        self.addCleanup(server.close)
        database = "topology_" + uuid.uuid4().hex
        with server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        connect = lambda: server.connect(database, row_factory=dict_row)
        plain = lambda: server.connect(database)            # the installer reads tuples
        before = [m for m in installer.discover_migrations() if m["version"] != "V069"]
        with patch.object(installer, "connect_repository", plain), \
                patch.object(installer, "discover_migrations", return_value=before), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()
        with connect() as conn:
            def add(name, kind, parent=None, active=True, manager=None):
                return conn.execute(
                    "INSERT INTO keystone.target (name, provider, target_type, environment, "
                    "parent_target_id, is_active, cluster_manager) VALUES (%s, 'PostgreSQL', %s, 'LAB', "
                    "%s, %s, %s) RETURNING target_id",
                    (name, kind, parent, active, manager)).fetchone()["target_id"]
            patroni = add("pg-cluster", "SYSTEM", manager="PATRONI")
            add("p1", "NODE", patroni)
            two = add("pg17-lab", "SYSTEM")
            add("primary", "NODE", two)
            add("replica", "NODE", two)
            one = add("laptop-pg", "SYSTEM")
            add("TTL", "NODE", one)
            add("gone", "NODE", one, active=False)
            lone = add("pg15-lab", "NODE")
            conn.commit()
        with patch.object(installer, "connect_repository", plain), contextlib.redirect_stdout(io.StringIO()):
            installer.main()
        with connect() as conn:
            got = {r["target_id"]: r["topology"] for r in conn.execute(
                "SELECT target_id, topology FROM keystone.target WHERE parent_target_id IS NULL")}
        self.assertEqual(got, {patroni: "CLUSTER", two: "CLUSTER", one: "STANDALONE", lone: None})


if __name__ == "__main__":
    unittest.main()
