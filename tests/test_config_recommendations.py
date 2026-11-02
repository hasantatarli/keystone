"""Configuration recommendations (ADR-0017 step 3a): units, calculations, ranges, statuses.

The calculations run against the real Dictionary of a clean install, so the
numbers tested are the numbers shipped.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_config_recommendations.py -v
"""

import contextlib
import io
import unittest
from unittest.mock import patch
import uuid

from psycopg import sql

from repository.common.server_profile import server_profile
from repository.install import install as installer
from repository.intelligence import config_dictionary
from repository.intelligence import config_recommendations as rec
from test_installer_findings import DisposablePostgres

GB, MB = 1024 ** 3, 1024 ** 2

RESTART_SETTINGS = {"shared_buffers", "huge_pages", "wal_buffers", "max_worker_processes",
                    "max_connections"}

# pg_settings defaults of PostgreSQL 17 for the settings Keystone recommends.
PG17_DEFAULTS = {
    "max_connections": ("100", None), "shared_buffers": ("16384", "8kB"),
    "effective_cache_size": ("524288", "8kB"), "work_mem": ("4096", "kB"),
    "maintenance_work_mem": ("65536", "kB"), "huge_pages": ("try", None),
    "max_wal_size": ("1024", "MB"), "min_wal_size": ("80", "MB"),
    "checkpoint_completion_target": ("0.9", None), "checkpoint_timeout": ("300", "s"),
    "wal_buffers": ("512", "8kB"), "random_page_cost": ("4", None),
    "effective_io_concurrency": ("1", None), "max_worker_processes": ("8", None),
    "max_parallel_workers": ("8", None), "max_parallel_workers_per_gather": ("2", None),
    "max_parallel_maintenance_workers": ("2", None), "log_min_duration_statement": ("-1", "ms"),
    "track_io_timing": ("off", None),
}


class UnitTests(unittest.TestCase):
    def test_pg_settings_units_become_bytes_and_seconds(self):
        cases = [
            ({"setting_value": "16384", "unit": "8kB"}, "BYTE", 128 * MB),
            ({"setting_value": "4096", "unit": "kB"}, "BYTE", 4 * MB),
            ({"setting_value": "1024", "unit": "MB"}, "BYTE", GB),
            ({"setting_value": "300", "unit": "s"}, "SECOND", 300),
            ({"setting_value": "250", "unit": "ms"}, "SECOND", 0.25),
            ({"setting_value": "-1", "unit": "ms"}, "SECOND", -1),          # disabled stays -1
            ({"setting_value": "0.9", "unit": None}, "NUMBER", 0.9),
            ({"setting_value": "try", "unit": None}, "ENUM", "try"),
            ({"setting_value": "off", "unit": None}, "BOOLEAN", "off"),
        ]
        for row, value_type, expected in cases:
            with self.subTest(row=row):
                self.assertEqual(rec.canonical(row, value_type), expected)

    def test_values_are_written_in_postgresql_syntax(self):
        self.assertEqual(rec.pg_value(4 * GB, "BYTE"), "4GB")
        self.assertEqual(rec.pg_value(1536 * MB, "BYTE"), "1536MB")
        self.assertEqual(rec.pg_value(900, "SECOND"), "15min")
        self.assertEqual(rec.pg_value(0.25, "SECOND"), "250ms")
        self.assertEqual(rec.pg_value(1, "SECOND"), "1s")
        self.assertEqual(rec.pg_value(0.9, "NUMBER"), "0.9")
        self.assertEqual(rec.pg_value(200.0, "COUNT"), "200")
        self.assertEqual(rec.pg_value(-1, "SECOND"), "-1")

    def test_ranges(self):
        self.assertTrue(rec.fits("on", {"values": ["try", "on"]}))
        self.assertFalse(rec.fits("off", {"values": ["try", "on"]}))
        self.assertTrue(rec.fits(9.0, {"low": 8.0, "high": None}))
        self.assertFalse(rec.fits(-1, {"low": 0.25, "high": 10}))
        self.assertEqual(rec.acceptable_text({"low": 8.0, "high": None}, "COUNT"), "≥ 8")
        self.assertEqual(rec.acceptable_text({"low": 2.4 * GB, "high": 6.4 * GB}, "BYTE"), "2457MB – 6553MB")


class RecommendationTests(unittest.TestCase):
    """Calculations on the Dictionary installed by the migrations."""

    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)
        database = "config_test_" + uuid.uuid4().hex
        with cls.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        with patch.object(installer, "connect_repository", lambda: cls.server.connect(database)), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()
        cls.conn = cls.server.connect(database)
        cls.addClassCleanup(cls.conn.close)
        cls.dictionary = config_dictionary.load_config_dictionary(cls.conn, "PostgreSQL")

    def facts(self, memory=16 * GB, cpus=4, disk=100 * GB, version=17, settings=None, replica=None):
        primary = dict(PG17_DEFAULTS)
        primary.update(settings or {})
        primary = {k: v for k, v in primary.items() if v is not None}
        rows = {1: {k: {"setting_value": v, "unit": u,
                        "context": "postmaster" if k in RESTART_SETTINGS else "user"}
                    for k, (v, u) in primary.items()}}
        if replica:
            rows[2] = {k: {"setting_value": v, "unit": u} for k, (v, u) in {**primary, **replica}.items()}
        return {"primary_id": 1, "version": version, "names": {1: "node-1", 2: "node-2"},
                "settings": rows, "memory": memory, "memory_node": 1, "cpus": cpus, "disk": disk,
                "nodes_without_host": []}

    def recommend(self, profile=None, **facts):
        results = rec.recommend(self.dictionary, self.facts(**facts), profile or server_profile({}))
        return {r["setting_key"]: r for r in results}

    def test_dedicated_oltp_server(self):
        r = self.recommend()
        self.assertEqual(r["shared_buffers"]["recommended_value"], 4 * GB)
        self.assertEqual(r["shared_buffers"]["status"], "DEVIATES")         # 128MB < 15 % of 16GB
        self.assertEqual(r["effective_cache_size"]["recommended_value"], 12 * GB)
        # (16GB - 4GB) / (100 connections × 4) = 30.7MB
        self.assertEqual(r["work_mem"]["recommended_value"], 30 * MB)
        self.assertEqual(r["maintenance_work_mem"]["recommended_value"], GB)
        self.assertEqual(r["max_wal_size"]["recommended_value"], 4 * GB)
        self.assertEqual(r["min_wal_size"]["recommended_value"], GB)
        self.assertEqual(r["max_parallel_workers"]["recommended_value"], 4)
        self.assertEqual(r["max_parallel_workers_per_gather"]["recommended_value"], 2)
        self.assertEqual(r["max_worker_processes"]["recommended_value"], 8)
        self.assertEqual(r["random_page_cost"]["recommended_value"], 1.1)
        self.assertEqual(r["random_page_cost"]["status"], "DEVIATES")       # HDD default on SSD
        self.assertEqual(r["huge_pages"]["status"], "FITS")
        self.assertEqual(r["work_mem"]["parameters_used"]["connection_factor"], 4)

    def test_workload_storage_and_dedication_change_the_numbers(self):
        profile = server_profile({"workload_type": "OLAP", "dedicated": False, "storage_type": "HDD"})
        r = self.recommend(profile)
        self.assertEqual(r["shared_buffers"]["recommended_value"], 2 * GB)  # half the memory is PostgreSQL's
        self.assertEqual(r["max_wal_size"]["recommended_value"], 10 * GB)   # 16GB capped at 10 % of the disk
        self.assertTrue(r["max_wal_size"]["calculation"]["capped"])
        self.assertEqual(r["random_page_cost"]["recommended_value"], 4.0)
        self.assertEqual(r["random_page_cost"]["status"], "FITS")
        self.assertEqual(r["effective_io_concurrency"]["recommended_value"], 2)

    def test_without_host_data_only_host_settings_are_not_assessed(self):
        r = self.recommend(memory=None, cpus=None, disk=None)
        not_assessed = {k for k, v in r.items() if v["status"] == "NOT_ASSESSED"}
        self.assertEqual(not_assessed, set(rec.NEEDS))
        self.assertEqual(r["shared_buffers"]["reason_code"], "no_memory")
        self.assertEqual(r["random_page_cost"]["status"], "DEVIATES")
        self.assertEqual(len([v for v in r.values() if v["status"] in ("FITS", "DEVIATES")]), 8)

    def test_few_cpus_keep_parallel_defaults(self):
        r = self.recommend(cpus=2)
        for key in ("max_worker_processes", "max_parallel_workers",
                    "max_parallel_workers_per_gather", "max_parallel_maintenance_workers"):
            self.assertEqual((r[key]["status"], r[key]["reason_code"]), ("NOT_APPLICABLE", "few_cpus"))

    def test_version_18_has_no_effective_io_concurrency(self):
        self.assertNotIn("effective_io_concurrency", self.recommend(version=18))
        self.assertIn("effective_io_concurrency", self.recommend(version=15))

    def test_disabled_slow_query_log_deviates(self):
        r = self.recommend(settings={"log_min_duration_statement": ("-1", "ms")})
        self.assertEqual(r["log_min_duration_statement"]["status"], "DEVIATES")
        r = self.recommend(settings={"log_min_duration_statement": ("1000", "ms")})
        self.assertEqual(r["log_min_duration_statement"]["status"], "FITS")

    def test_lower_bound_only_for_worker_processes(self):
        r = self.recommend(settings={"max_worker_processes": ("32", None)})   # extensions may need more
        self.assertEqual(r["max_worker_processes"]["status"], "FITS")
        r = self.recommend(settings={"max_worker_processes": ("4", None)})
        self.assertEqual(r["max_worker_processes"]["status"], "DEVIATES")

    def test_other_nodes_with_another_value_are_noted(self):
        r = self.recommend(replica={"work_mem": ("16384", "kB")})
        self.assertEqual(r["work_mem"]["node_differences"], [{"node": "node-2", "value": "16MB"}])
        self.assertIsNone(r["shared_buffers"]["node_differences"])

    def test_setting_missing_from_the_snapshot_is_not_assessed(self):
        r = self.recommend(settings={"checkpoint_timeout": None})
        self.assertEqual((r["checkpoint_timeout"]["status"], r["checkpoint_timeout"]["reason_code"]),
                         ("NOT_ASSESSED", "setting_not_collected"))

    def test_restart_and_assumed_profile_are_kept_with_the_result(self):
        r = self.recommend()                                   # nothing given: every field assumed
        self.assertTrue(r["shared_buffers"]["restart_required"])
        self.assertFalse(r["work_mem"]["restart_required"])
        self.assertEqual(r["random_page_cost"]["assumptions"], ["storage_type"])
        self.assertEqual(r["work_mem"]["assumptions"], ["dedicated", "workload_type"])
        self.assertIsNone(r["checkpoint_timeout"]["assumptions"])
        given = server_profile({"workload_type": "OLTP", "dedicated": True, "storage_type": "SSD"})
        self.assertIsNone(self.recommend(given)["random_page_cost"]["assumptions"])


if __name__ == "__main__":
    unittest.main()
