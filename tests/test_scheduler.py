"""Tests for the generic scheduler, the collector job adapter and the agent (ADR-0015).

Scheduler rules are tested with a fake clock and fake adapter (no database);
the collector adapter, the single-scheduler lock and one agent cycle run
against a disposable PostgreSQL repository.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_scheduler.py -v
"""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import unittest
from unittest.mock import MagicMock, patch
import uuid

from psycopg import sql
from psycopg.rows import dict_row

from repository.agent.agent import Agent
from repository.agent.jobs import CollectorJobs
from repository.agent.scheduler import (
    JobAdapter,
    ScheduledItem,
    Scheduler,
    try_acquire_scheduler_lock,
)
from repository.install import install as installer
from test_installer_findings import DisposablePostgres


T0 = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class FakeAdapter(JobAdapter):
    """Items are fixed; 'history' is what a real adapter would read back."""

    job_type = "FAKE"

    def __init__(self, interval=60, record_history=True, fail_runs=False):
        self.interval = interval
        self.record_history = record_history
        self.fail_runs = fail_runs
        self.history = None
        self.runs = []

    def list_items(self, conn):
        return [ScheduledItem("FAKE", ("a",), self.interval, self.history)]

    def run(self, conn, item, now):
        self.runs.append(now)
        if self.record_history:
            self.history = now
        if self.fail_runs:
            raise RuntimeError("job failed")


class SchedulerRuleTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.conn = MagicMock()

    def tick(self, scheduler, seconds=0):
        self.clock.advance(seconds)
        return scheduler.tick(self.conn)

    def test_never_run_item_is_due_immediately(self):
        adapter = FakeAdapter()
        self.tick(Scheduler([adapter], clock=self.clock))
        self.assertEqual(adapter.runs, [T0])

    def test_item_is_not_due_before_interval_and_due_at_interval(self):
        adapter = FakeAdapter(interval=60)
        scheduler = Scheduler([adapter], clock=self.clock)

        self.tick(scheduler)
        self.tick(scheduler, 59)
        self.assertEqual(len(adapter.runs), 1)
        self.tick(scheduler, 1)
        self.assertEqual(len(adapter.runs), 2)

    def test_last_start_comes_from_history(self):
        adapter = FakeAdapter(interval=60)
        adapter.history = T0 - timedelta(seconds=30)   # ran 30 s ago elsewhere
        scheduler = Scheduler([adapter], clock=self.clock)

        self.tick(scheduler)
        self.assertEqual(adapter.runs, [])
        self.tick(scheduler, 30)
        self.assertEqual(len(adapter.runs), 1)

    def test_unrecorded_run_is_not_repeated_every_tick(self):
        # The run happened but its history could not be written: the
        # in-memory dispatch time keeps the interval.
        adapter = FakeAdapter(interval=60, record_history=False)
        scheduler = Scheduler([adapter], clock=self.clock)

        for _ in range(5):
            self.tick(scheduler, 10)
        self.assertEqual(len(adapter.runs), 1)

    def test_failed_run_counts_as_run(self):
        adapter = FakeAdapter(interval=60, record_history=False, fail_runs=True)
        scheduler = Scheduler([adapter], clock=self.clock)

        with self.assertLogs("keystone.scheduler", level="ERROR"):
            self.tick(scheduler)
        self.tick(scheduler, 30)
        self.assertEqual(len(adapter.runs), 1)
        with self.assertLogs("keystone.scheduler", level="ERROR"):
            self.tick(scheduler, 30)
        self.assertEqual(len(adapter.runs), 2)

    def test_overdue_item_runs_once_not_catching_up(self):
        adapter = FakeAdapter(interval=60)
        adapter.history = T0 - timedelta(hours=3)   # agent was down for 3 hours
        scheduler = Scheduler([adapter], clock=self.clock)

        self.tick(scheduler)
        self.tick(scheduler, 1)
        self.assertEqual(len(adapter.runs), 1)

    def test_failing_adapter_does_not_stop_others(self):
        broken = FakeAdapter()
        broken.list_items = MagicMock(side_effect=RuntimeError("cannot list"))
        healthy = FakeAdapter()

        with self.assertLogs("keystone.scheduler", level="ERROR"):
            self.tick(Scheduler([broken, healthy], clock=self.clock))
        self.assertEqual(len(healthy.runs), 1)


class SchedulerRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = DisposablePostgres()
        cls.server.start()
        cls.addClassCleanup(cls.server.close)

        cls.template = "scheduler_template_" + uuid.uuid4().hex
        with cls.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.template)))

        def connect_plain():
            return cls.server.connect(cls.template)

        with patch.object(installer, "connect_repository", connect_plain), \
                contextlib.redirect_stdout(io.StringIO()):
            installer.main()

    def setUp(self):
        self.database = "scheduler_test_" + uuid.uuid4().hex
        with self.server.connect(autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(self.database), sql.Identifier(self.template)))
        self.conn = self.connect()
        self.addCleanup(self.conn.close)

        self.target_id = self.conn.execute(
            "INSERT INTO keystone.target (name, provider, target_type, environment) "
            "VALUES ('sched-target', 'PostgreSQL', 'SYSTEM', 'TEST') RETURNING target_id"
        ).fetchone()["target_id"]
        self.conn.commit()

    def connect(self):
        return self.server.connect(self.database, row_factory=dict_row)

    def assign(self, collector_key, mode="SCHEDULED", interval=60, enabled=True):
        row = self.conn.execute(
            """
            INSERT INTO keystone.collector_assignment
                (collector_id, target_id, execution_mode, interval_seconds, is_enabled)
            SELECT collector_id, %s, %s, %s, %s
            FROM keystone.collector_definition WHERE collector_key = %s
            RETURNING assignment_id
            """,
            (self.target_id, mode, interval if mode == "SCHEDULED" else None,
             enabled, collector_key),
        ).fetchone()
        self.conn.commit()
        return row["assignment_id"]

    def record_run(self, assignment_id, started_at, status="SUCCESS"):
        self.conn.execute(
            """
            INSERT INTO keystone.collector_run_history
                (assignment_id, started_at, finished_at, status, executed_by)
            VALUES (%s, %s, %s, %s, 'test')
            """,
            (assignment_id, started_at, started_at, status),
        )
        self.conn.commit()

    def queued(self):
        return [r["assignment_id"] for r in self.conn.execute(
            "SELECT assignment_id FROM keystone.collection_queue "
            "WHERE status = 'WAITING' ORDER BY assignment_id").fetchall()]

    def tick(self, now):
        return Scheduler([CollectorJobs()], clock=lambda: now).tick(self.conn)

    # ---------------------------------------------------------------- adapter

    def test_due_scheduled_assignment_is_queued(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=60)
        self.tick(datetime.now(timezone.utc))
        self.assertEqual(self.queued(), [assignment])

    def test_recent_run_is_not_due_yet(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=600)
        now = datetime.now(timezone.utc)
        self.record_run(assignment, now - timedelta(seconds=100))

        self.tick(now)
        self.assertEqual(self.queued(), [])
        self.tick(now + timedelta(seconds=500))
        self.assertEqual(self.queued(), [assignment])

    def test_failed_last_run_still_counts(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=600)
        now = datetime.now(timezone.utc)
        self.record_run(assignment, now - timedelta(seconds=100), status="FAILED")

        self.tick(now)
        self.assertEqual(self.queued(), [])

    def test_on_demand_and_disabled_assignments_are_ignored(self):
        self.assign("PG_ACTIVITY_SNAPSHOT", mode="ON_DEMAND")
        self.assign("PG_REPLICATION_SLOTS", enabled=False)
        self.tick(datetime.now(timezone.utc))
        self.assertEqual(self.queued(), [])

    def test_assignment_already_in_queue_is_not_duplicated(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=60)
        self.conn.execute(
            "INSERT INTO keystone.collection_queue (assignment_id, status, scheduled_at) "
            "VALUES (%s, 'WAITING', now())", (assignment,))
        self.conn.commit()

        dispatched = self.tick(datetime.now(timezone.utc))
        self.assertEqual(dispatched, [])
        self.assertEqual(self.queued(), [assignment])

    def test_retry_exhausted_task_does_not_block_new_runs(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=60)
        self.conn.execute(
            "INSERT INTO keystone.collection_queue (assignment_id, status, scheduled_at) "
            "VALUES (%s, 'RETRY_EXHAUSTED', now())", (assignment,))
        self.conn.commit()

        self.tick(datetime.now(timezone.utc))
        self.assertEqual(self.queued(), [assignment])

    # ------------------------------------------------------------ lock, agent

    def test_only_one_session_holds_the_scheduler_lock(self):
        first, second = self.connect(), self.connect()
        self.addCleanup(first.close)
        self.addCleanup(second.close)

        self.assertTrue(try_acquire_scheduler_lock(first))
        self.assertFalse(try_acquire_scheduler_lock(second))
        first.close()
        self.assertTrue(try_acquire_scheduler_lock(second))

    def test_agent_cycle_schedules_then_runs_worker(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=60)
        worker_runs = []
        agent = Agent(self.connect, [CollectorJobs()], lambda: worker_runs.append(1))
        self.addCleanup(agent._release_lock)

        agent.run_cycle()

        self.assertEqual(self.queued(), [assignment])
        self.assertEqual(worker_runs, [1])

    def test_second_agent_does_not_schedule_but_still_runs_worker(self):
        self.assign("PG_ACTIVITY_SNAPSHOT", interval=60)
        holder = self.connect()
        self.addCleanup(holder.close)
        self.assertTrue(try_acquire_scheduler_lock(holder))

        worker_runs = []
        agent = Agent(self.connect, [CollectorJobs()], lambda: worker_runs.append(1))
        agent.run_cycle()

        self.assertEqual(self.queued(), [])
        self.assertEqual(worker_runs, [1])

    def test_agent_survives_worker_failure(self):
        def broken_worker():
            raise RuntimeError("worker crashed")

        agent = Agent(self.connect, [CollectorJobs()], broken_worker)
        self.addCleanup(agent._release_lock)

        with self.assertLogs("keystone.agent", level="ERROR"):
            agent.run_cycle()
            agent.run_cycle()

    def test_agent_reacquires_lock_after_losing_its_session(self):
        agent = Agent(self.connect, [CollectorJobs()], lambda: None)
        self.addCleanup(agent._release_lock)
        self.assertTrue(agent.holds_scheduler_lock())

        agent._lock_conn.close()   # e.g. network blip killed the session
        with self.assertLogs("keystone.agent", level="WARNING"):
            self.assertFalse(agent.holds_scheduler_lock())
        self.assertTrue(agent.holds_scheduler_lock())


if __name__ == "__main__":
    unittest.main()
