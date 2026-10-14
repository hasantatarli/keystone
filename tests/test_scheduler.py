"""Tests for the scheduler, the collector job adapter, the worker pool and the agent (ADR-0015).

Scheduler rules are tested with a fake clock and fake adapter (no database);
the collector adapter, task claiming limits, the single-scheduler lock and
the agent run against a disposable PostgreSQL repository.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_scheduler.py -v
"""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import uuid

from psycopg import sql
from psycopg.rows import dict_row

from repository.agent.agent import Agent
from repository.agent.jobs import CollectorJobs
from repository.agent import pool as pool_module
from repository.agent.pool import WorkerPool, load_duration_stats, long_running_threshold
from repository.agent.scheduler import (
    JobAdapter,
    ScheduledItem,
    Scheduler,
    slot_start,
    try_acquire_scheduler_lock,
)
from repository.worker import worker
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

    def __init__(self, clock, interval=60, record_history=True, fail_runs=False):
        self.clock = clock
        self.interval = interval
        self.record_history = record_history
        self.fail_runs = fail_runs
        self.history = None          # last start
        self.finished = None         # last finish
        self.busy = False
        self.runs = []               # actual start times
        self.planned = []            # planned slot per run

    def list_items(self, conn):
        return [ScheduledItem("FAKE", ("a",), self.interval, self.history,
                              self.finished, self.busy)]

    def run(self, conn, item, planned_at):
        self.runs.append(self.clock())
        self.planned.append(planned_at)
        if self.record_history:
            self.history = self.finished = self.clock()
        if self.fail_runs:
            raise RuntimeError("job failed")


class SchedulerRuleTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.conn = MagicMock()

    def tick(self, scheduler, seconds=0):
        self.clock.advance(seconds)
        return scheduler.tick(self.conn)

    def adapter(self, **kwargs):
        return FakeAdapter(self.clock, **kwargs)

    def at(self, seconds):
        return T0 + timedelta(seconds=seconds)

    def test_never_run_item_is_due_immediately(self):
        self.clock.advance(10)
        adapter = self.adapter()
        self.tick(Scheduler([adapter], clock=self.clock))
        self.assertEqual(adapter.runs, [self.at(10)])
        self.assertEqual(adapter.planned, [self.at(10)])

    def test_runs_follow_the_fixed_grid_without_drift(self):
        # First run at :10 (never ran), then on every minute boundary.
        adapter = self.adapter(interval=60)
        scheduler = Scheduler([adapter], clock=self.clock)

        self.tick(scheduler, 10)
        self.tick(scheduler, 49)          # 12:00:59
        self.assertEqual(len(adapter.runs), 1)
        self.tick(scheduler, 1)           # 12:01:00
        self.tick(scheduler, 62)          # 12:02:02, a little late
        self.assertEqual(adapter.planned,
                         [self.at(10), self.at(60), self.at(120)])

    def test_slot_start_is_aligned_to_the_clock(self):
        now = datetime(2026, 10, 14, 12, 34, 56, tzinfo=timezone.utc)
        self.assertEqual(slot_start(now, 60), now.replace(second=0))
        self.assertEqual(slot_start(now, 3600), now.replace(minute=0, second=0))

    def test_recent_run_from_history_is_not_repeated_in_same_slot(self):
        adapter = self.adapter(interval=60)
        adapter.history = adapter.finished = self.at(10)   # ran elsewhere at 12:00:10
        scheduler = Scheduler([adapter], clock=self.clock)

        self.tick(scheduler, 30)
        self.assertEqual(adapter.runs, [])
        self.tick(scheduler, 30)          # 12:01:00
        self.assertEqual(len(adapter.runs), 1)

    def test_slot_missed_by_a_long_run_is_skipped(self):
        # Started 12:00:00, finished 12:01:30: the 12:01 slot is skipped.
        adapter = self.adapter(interval=60)
        adapter.history, adapter.finished = T0, self.at(90)
        scheduler = Scheduler([adapter], clock=self.clock)

        self.tick(scheduler, 91)
        self.tick(scheduler, 28)          # 12:01:59
        self.assertEqual(adapter.runs, [])
        self.tick(scheduler, 1)           # 12:02:00
        self.assertEqual(adapter.planned, [self.at(120)])

    def test_busy_item_is_not_dispatched(self):
        adapter = self.adapter(interval=60)
        adapter.busy = True
        self.tick(Scheduler([adapter], clock=self.clock))
        self.assertEqual(adapter.runs, [])

    def test_unrecorded_run_is_not_repeated_every_tick(self):
        # The run happened but its history could not be written: the
        # in-memory dispatch time keeps it to one run per slot.
        adapter = self.adapter(interval=60, record_history=False)
        scheduler = Scheduler([adapter], clock=self.clock)

        for _ in range(5):
            self.tick(scheduler, 10)
        self.assertEqual(len(adapter.runs), 1)

    def test_failed_run_counts_as_run(self):
        adapter = self.adapter(interval=60, record_history=False, fail_runs=True)
        scheduler = Scheduler([adapter], clock=self.clock)

        with self.assertLogs("keystone.scheduler", level="ERROR"):
            self.tick(scheduler)
        self.tick(scheduler, 30)
        self.assertEqual(len(adapter.runs), 1)
        with self.assertLogs("keystone.scheduler", level="ERROR"):
            self.tick(scheduler, 30)
        self.assertEqual(len(adapter.runs), 2)

    def test_after_downtime_item_runs_once_as_catch_up(self):
        adapter = self.adapter(interval=60)
        adapter.history = adapter.finished = T0 - timedelta(hours=3)
        scheduler = Scheduler([adapter], clock=self.clock)

        self.tick(scheduler, 37)
        self.tick(scheduler, 1)
        self.assertEqual(adapter.runs, [self.at(37)])
        self.assertEqual(adapter.planned, [self.at(37)])   # late: planned "now", not 12:00

    def test_slot_start_with_offset(self):
        now = datetime(2026, 10, 14, 12, 34, 56, tzinfo=timezone.utc)
        self.assertEqual(slot_start(now, 60, 30), now.replace(second=30))
        early = now.replace(second=10)
        self.assertEqual(slot_start(early, 60, 30), now.replace(minute=33, second=30))

    def test_item_with_offset_runs_after_the_boundary(self):
        clock = self.clock

        class OffsetAdapter(FakeAdapter):
            def list_items(self, conn):
                return [ScheduledItem("FAKE", ("o",), 60, self.history, self.finished,
                                      offset_seconds=30)]

        adapter = OffsetAdapter(clock)
        adapter.history = adapter.finished = T0 - timedelta(seconds=10)   # 11:59:50
        scheduler = Scheduler([adapter], clock=clock)

        self.tick(scheduler, 29)          # 12:00:29
        self.assertEqual(adapter.runs, [])
        self.tick(scheduler, 1)           # 12:00:30
        self.assertEqual(adapter.planned, [self.at(30)])
        self.assertEqual(scheduler.next_wake_at, self.at(90))

    def no_catch_up_adapter(self):
        class NoCatchUpAdapter(FakeAdapter):
            def list_items(self, conn):
                return [ScheduledItem("FAKE", ("n",), 60, self.history, self.finished,
                                      offset_seconds=30, catch_up=False)]
        return NoCatchUpAdapter(self.clock)

    def test_without_catch_up_a_late_start_waits_for_next_slot(self):
        # Agent starts at 12:00:50, 20 s after the 12:00:30 slot: wait for 12:01:30.
        adapter = self.no_catch_up_adapter()
        adapter.history = adapter.finished = T0 - timedelta(hours=3)
        scheduler = Scheduler([adapter], clock=self.clock)

        self.tick(scheduler, 50)          # 12:00:50, 20 s late
        self.assertEqual(adapter.runs, [])
        self.tick(scheduler, 40)          # 12:01:30
        self.assertEqual(adapter.planned, [self.at(90)])

    def test_without_catch_up_never_run_item_also_waits(self):
        adapter = self.no_catch_up_adapter()
        scheduler = Scheduler([adapter], clock=self.clock)

        self.tick(scheduler, 50)
        self.assertEqual(adapter.runs, [])
        self.tick(scheduler, 40)
        self.assertEqual(adapter.planned, [self.at(90)])

    def test_next_wake_is_the_next_slot_boundary(self):
        scheduler = Scheduler([self.adapter(interval=60)], clock=self.clock)
        self.tick(scheduler, 10)
        self.assertEqual(scheduler.next_wake_at, self.at(60))

    def test_failing_adapter_does_not_stop_others(self):
        broken = self.adapter()
        broken.list_items = MagicMock(side_effect=RuntimeError("cannot list"))
        healthy = self.adapter()

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

    def add_target(self, name, max_concurrent_tasks=3):
        target_id = self.conn.execute(
            "INSERT INTO keystone.target (name, provider, target_type, environment, "
            "max_concurrent_tasks) VALUES (%s, 'PostgreSQL', 'SYSTEM', 'TEST', %s) "
            "RETURNING target_id", (name, max_concurrent_tasks)
        ).fetchone()["target_id"]
        self.conn.execute(
            "INSERT INTO keystone.target_connection (target_id, connection_name, host, "
            "port, database_name, username, auth_type, credential_data, connection_purpose) "
            "VALUES (%s, 'db', 'localhost', 5432, 'postgres', 'u', 'PASSWORD', 'x', 'PRIMARY')",
            (target_id,))
        self.conn.commit()
        return target_id

    def sql_collectors(self, count):
        return [r["collector_key"] for r in self.conn.execute(
            "SELECT collector_key FROM keystone.collector_definition "
            "WHERE execution_type = 'SQL' AND is_active ORDER BY collector_key LIMIT %s",
            (count,)).fetchall()]

    def assign(self, collector_key, mode="SCHEDULED", interval=60, enabled=True,
               target_id=None):
        row = self.conn.execute(
            """
            INSERT INTO keystone.collector_assignment
                (collector_id, target_id, execution_mode, interval_seconds, is_enabled)
            SELECT collector_id, %s, %s, %s, %s
            FROM keystone.collector_definition WHERE collector_key = %s
            RETURNING assignment_id
            """,
            (target_id or self.target_id, mode, interval if mode == "SCHEDULED" else None,
             enabled, collector_key),
        ).fetchone()
        self.conn.commit()
        return row["assignment_id"]

    def enqueue(self, assignment_id, scheduled_at="now()"):
        self.conn.execute(
            "INSERT INTO keystone.collection_queue (assignment_id, status, scheduled_at) "
            f"VALUES (%s, 'WAITING', {scheduled_at})", (assignment_id,))
        self.conn.commit()

    def claim(self, limit=10):
        with self.connect() as conn:
            return worker.claim_tasks(conn, worker_id="test-worker", limit=limit)

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

    def test_recent_run_is_not_due_until_next_slot(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=600)
        base = slot_start(datetime.now(timezone.utc), 600)
        self.record_run(assignment, base + timedelta(seconds=50))

        self.tick(base + timedelta(seconds=150))
        self.assertEqual(self.queued(), [])
        self.tick(base + timedelta(seconds=600))
        self.assertEqual(self.queued(), [assignment])

    def test_planned_slot_is_stored_as_scheduled_at(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=600)
        base = slot_start(datetime.now(timezone.utc), 600)
        self.record_run(assignment, base + timedelta(seconds=50))

        self.tick(base + timedelta(seconds=603))
        scheduled = self.conn.execute(
            "SELECT scheduled_at FROM keystone.collection_queue WHERE assignment_id = %s",
            (assignment,)).fetchone()["scheduled_at"]
        self.assertEqual(scheduled, base + timedelta(seconds=600))

    def test_failed_last_run_still_counts(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=600)
        base = slot_start(datetime.now(timezone.utc), 600)
        self.record_run(assignment, base + timedelta(seconds=50), status="FAILED")

        self.tick(base + timedelta(seconds=150))
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

    # ------------------------------------------------------- long-running stats

    def test_duration_stats_use_recent_successful_runs_only(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=60)
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        durations = [1000] * 6 + [3_000_000]           # one 50-minute outlier
        for i, ms in enumerate(durations):
            self.conn.execute(
                "INSERT INTO keystone.collector_run_history (assignment_id, started_at, "
                "finished_at, status, execution_time_ms, executed_by) "
                "VALUES (%s, %s, %s, 'SUCCESS', %s, 'test')",
                (assignment, start + timedelta(minutes=i), start + timedelta(minutes=i), ms))
        self.record_run(assignment, start + timedelta(minutes=30), status="TIMEOUT")
        self.conn.commit()

        median, runs, expected = load_duration_stats(self.conn, [assignment])[assignment]
        self.assertEqual((median, runs, expected), (1.0, 7, None))

        self.conn.execute("UPDATE keystone.collector_assignment SET expected_max_seconds = 3600 "
                          "WHERE assignment_id = %s", (assignment,))
        self.conn.commit()
        self.assertEqual(load_duration_stats(self.conn, [assignment])[assignment][2], 3600)

    # --------------------------------------------------------------- claiming

    def test_claim_respects_per_target_limit(self):
        busy = self.add_target("busy-target", max_concurrent_tasks=2)
        other = self.add_target("other-target", max_concurrent_tasks=2)
        keys = self.sql_collectors(3)
        busy_tasks = [self.assign(k, target_id=busy) for k in keys]
        other_task = self.assign(keys[0], target_id=other)
        for assignment in busy_tasks + [other_task]:
            self.enqueue(assignment)

        claimed = [t["assignment_id"] for t in self.claim()]
        self.assertEqual(len([a for a in claimed if a in busy_tasks]), 2)
        self.assertIn(other_task, claimed)

        # Running tasks keep the slots taken: nothing more for the busy target.
        self.assertEqual(self.claim(), [])

    def test_claim_returns_planned_time(self):
        assignment = self.assign(self.sql_collectors(1)[0],
                                 target_id=self.add_target("planned-target"))
        self.enqueue(assignment, "now() - interval '45 seconds'")

        task = self.claim()[0]
        lag = (task["started_at"] - task["scheduled_at"]).total_seconds()
        self.assertGreaterEqual(lag, 45)

    def test_future_task_is_not_claimed(self):
        assignment = self.assign(self.sql_collectors(1)[0],
                                 target_id=self.add_target("future-target"))
        self.enqueue(assignment, "now() + interval '1 hour'")
        self.assertEqual(self.claim(), [])

    # ------------------------------------------------------------ lock, agent

    def test_only_one_session_holds_the_scheduler_lock(self):
        first, second = self.connect(), self.connect()
        self.addCleanup(first.close)
        self.addCleanup(second.close)

        self.assertTrue(try_acquire_scheduler_lock(first))
        self.assertFalse(try_acquire_scheduler_lock(second))
        first.close()
        self.assertTrue(try_acquire_scheduler_lock(second))

    def make_agent(self):
        pool = MagicMock()
        agent = Agent(self.connect, [CollectorJobs()], pool)
        self.addCleanup(agent._release_lock)
        return agent, pool

    def test_agent_schedules_and_wakes_the_pool(self):
        assignment = self.assign("PG_ACTIVITY_SNAPSHOT", interval=60)
        agent, pool = self.make_agent()

        sleep = agent.schedule_once()

        self.assertEqual(self.queued(), [assignment])
        pool.wake.assert_called()
        self.assertLessEqual(sleep, 60.1)

    def test_second_agent_does_not_schedule(self):
        self.assign("PG_ACTIVITY_SNAPSHOT", interval=60)
        holder = self.connect()
        self.addCleanup(holder.close)
        self.assertTrue(try_acquire_scheduler_lock(holder))

        agent, pool = self.make_agent()
        self.assertEqual(agent.schedule_once(), agent.poll_seconds)
        self.assertEqual(self.queued(), [])

    def test_agent_reacquires_lock_after_losing_its_session(self):
        agent, _ = self.make_agent()
        self.assertTrue(agent.holds_scheduler_lock())

        agent._lock_conn.close()   # e.g. network blip killed the session
        with self.assertLogs("keystone.agent", level="WARNING"):
            self.assertFalse(agent.holds_scheduler_lock())
        self.assertTrue(agent.holds_scheduler_lock())


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class WorkerPoolTests(unittest.TestCase):
    """Pool behaviour with a fake claim and fake task processing (no database)."""

    def setUp(self):
        self.waiting = []            # tasks the fake queue will hand out
        self.claim_limits = []
        self.release = threading.Event()
        self.started = []

    def claim(self, conn, worker_id, limit):
        self.claim_limits.append(limit)
        tasks, self.waiting = self.waiting[:limit], self.waiting[limit:]
        return tasks

    def process(self, task):
        self.started.append(task["task_id"])
        if task.get("fail"):
            raise RuntimeError("collector failed")
        self.release.wait(5)

    def make_pool(self, max_workers=3, **kwargs):
        pool = WorkerPool(lambda: FakeConnection(), "test-worker", max_workers=max_workers,
                          claim=self.claim, process=self.process,
                          recover=lambda conn: [], **kwargs)
        self.addCleanup(pool.executor.shutdown, wait=True)
        self.addCleanup(self.release.set)
        return pool

    def tasks(self, *ids, **extra):
        return [dict(task_id=i, assignment_id=i, **extra) for i in ids]

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            if time.monotonic() > deadline:
                self.fail("condition not reached")
            time.sleep(0.01)

    def test_claims_only_free_slots(self):
        self.waiting = self.tasks(1, 2, 3, 4, 5)
        pool = self.make_pool(max_workers=3)

        self.assertEqual(pool.fill(), 3)
        self.assertEqual(pool.fill(), 0)       # full: claim not even called
        self.assertEqual(self.claim_limits, [3])

    def test_freed_slot_takes_next_task_without_waiting_for_others(self):
        self.waiting = self.tasks(1, 2, 3) + self.tasks(4, fail=True)
        self.waiting = [self.waiting[3]] + self.waiting[:3]   # failing task first
        pool = self.make_pool(max_workers=3)

        with self.assertLogs("keystone.pool", level="ERROR"):
            pool.fill()
            self.wait_for(lambda: pool.running_count == 2)
        self.assertEqual(pool.fill(), 1)        # slot of the finished task reused
        self.assertEqual(self.claim_limits, [3, 1])

    def test_late_start_warns_once_per_minute(self):
        start = T0 + timedelta(seconds=45)
        self.waiting = self.tasks(1, 2, scheduled_at=T0, started_at=start)
        pool = self.make_pool(max_workers=5)

        with self.assertLogs("keystone.pool", level="WARNING") as logs:
            pool.fill()
        self.assertEqual(len([r for r in logs.records if r.levelname == "WARNING"]), 1)

    def test_long_running_threshold(self):
        self.assertEqual(long_running_threshold(None, 0), 600)          # no history
        self.assertEqual(long_running_threshold(30, 4), 600)            # too little history
        self.assertEqual(long_running_threshold(30, 5), 120)            # floor 2 min
        self.assertEqual(long_running_threshold(60, 30), 180)           # weekend example: 3 min
        self.assertEqual(long_running_threshold(60, 30, 3600), 3600)    # manual override

    def test_long_running_task_is_reported_once_and_not_stopped(self):
        clock = [0.0]
        self.waiting = self.tasks(1, collector_key="PG_TABLE_CAPACITY", target_name="lab")
        pool = self.make_pool(monotonic=lambda: clock[0])
        pool.fill()

        stats = {1: (60.0, 30, None)}                 # usually 1 min -> threshold 180 s
        with patch.object(pool_module, "load_duration_stats", return_value=stats):
            clock[0] = 170
            with self.assertNoLogs("keystone.pool", level="WARNING"):
                pool.check_long_running()
            clock[0] = 200
            with self.assertLogs("keystone.pool", level="WARNING") as logs:
                pool.check_long_running()
            clock[0] = 400
            with self.assertNoLogs("keystone.pool", level="WARNING"):
                pool.check_long_running()

        self.assertIn("PG_TABLE_CAPACITY on lab running for 3 min", logs.output[0])
        self.assertEqual(pool.running_count, 1)       # still running

    def test_short_tasks_do_not_touch_the_repository(self):
        self.waiting = self.tasks(1)
        pool = self.make_pool(monotonic=lambda: 0.0)
        pool.fill()
        with patch.object(pool_module, "load_duration_stats") as stats:
            pool.check_long_running()
        stats.assert_not_called()

    def test_run_stops_when_stop_event_is_set(self):
        pool = self.make_pool()
        stop = threading.Event()
        runner = threading.Thread(target=pool.run, args=(stop, 10))
        runner.start()
        stop.set()
        pool.wake()
        runner.join(5)
        self.assertFalse(runner.is_alive())


if __name__ == "__main__":
    unittest.main()
