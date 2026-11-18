"""Repository connection settings: one place, no lab or superuser defaults.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_repository_settings.py -v
"""

import unittest
from unittest.mock import patch

from repository.common import repository_settings as rs
from repository.install import install
from repository.intelligence import assessment_engine
from repository.worker import worker


class RepositorySettingsTests(unittest.TestCase):
    def test_missing_user_stops_with_a_message(self):
        with self.assertRaises(rs.RepositorySettingsError) as raised:
            rs.repository_settings({"KEYSTONE_REPOSITORY_DB": "x"})
        self.assertIn("KEYSTONE_REPOSITORY_USER", str(raised.exception))
        # A SystemExit: a command ends with the message, no traceback.
        self.assertIsInstance(raised.exception, SystemExit)

    def test_blank_user_counts_as_missing(self):
        with self.assertRaises(rs.RepositorySettingsError):
            rs.repository_settings({"KEYSTONE_REPOSITORY_USER": "  "})

    def test_defaults_are_the_product_not_the_lab(self):
        got = rs.repository_settings({"KEYSTONE_REPOSITORY_USER": "keystone_app"})
        self.assertEqual(got, {"host": "localhost", "port": 5432, "dbname": "keystone",
                               "user": "keystone_app", "password": None})

    def test_every_variable_is_used(self):
        got = rs.repository_settings({
            "KEYSTONE_REPOSITORY_HOST": "db", "KEYSTONE_REPOSITORY_PORT": "6432",
            "KEYSTONE_REPOSITORY_DB": "keystone_lab", "KEYSTONE_REPOSITORY_USER": "postgres",
            "KEYSTONE_REPOSITORY_PASSWORD": "p"})
        self.assertEqual(got, {"host": "db", "port": 6432, "dbname": "keystone_lab",
                               "user": "postgres", "password": "p"})

    def test_read_when_connecting_not_at_import(self):
        # All three entry points use the same settings, read at connect time.
        for module in (install, assessment_engine, worker):
            with self.subTest(module=module.__name__), \
                    patch.dict("os.environ", {"KEYSTONE_REPOSITORY_USER": "u",
                                              "KEYSTONE_REPOSITORY_DB": "d"}, clear=True), \
                    patch("psycopg.connect") as connect:
                module.connect_repository()
                kwargs = connect.call_args.kwargs
                self.assertEqual((kwargs["user"], kwargs["dbname"]), ("u", "d"))

    def test_no_lab_values_left_in_product_code(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / "repository"
        hits = [str(p) for p in root.rglob("*.py") if "keystone_lab" in p.read_text(encoding="utf-8")]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
