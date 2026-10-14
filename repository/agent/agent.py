"""Keystone Agent (ADR-0015): long-running service that schedules jobs and runs them.

Like SQL Server Agent it runs independently of any user interface; run it under
systemd or as a Windows service. All state lives in the repository, so a
restart continues where it stopped. More agents can run side by side: only one
schedules (advisory lock), all of them take work from the shared queue.

    python -m repository.agent.agent [--max-workers 20] [--poll-seconds 10]
"""

import argparse
from datetime import datetime, timezone
import signal
import threading
import uuid

from repository.agent.jobs import SCHEDULED_JOB_TYPES
from repository.agent.pool import DEFAULT_MAX_WORKERS, WorkerPool
from repository.agent.scheduler import Scheduler, try_acquire_scheduler_lock
from repository.common.logging_config import configure_logging, get_logger
from repository.worker import worker


logger = get_logger("agent")

DEFAULT_POLL_SECONDS = 10
MIN_SLEEP_SECONDS = 0.05


class Agent:
    """Scheduler thread (only the lock holder schedules) + continuous worker pool."""

    def __init__(self, connect, adapters, pool, poll_seconds=DEFAULT_POLL_SECONDS,
                 clock=None):
        self.connect = connect
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.adapters = list(adapters)
        self.scheduler = Scheduler(self.adapters, clock=self.clock)
        self.pool = pool
        self.poll_seconds = poll_seconds
        self.stop_event = threading.Event()
        self._lock_conn = None

    def holds_scheduler_lock(self):
        """Keep a dedicated session holding the advisory lock; re-acquire if it was lost."""
        try:
            if self._lock_conn is not None:
                self._lock_conn.execute("SELECT 1")   # still alive?
                self._lock_conn.commit()
                return True

            conn = self.connect()
            if try_acquire_scheduler_lock(conn):
                self._lock_conn = conn
                logger.info("Scheduler lock acquired; this agent schedules jobs.",
                            extra={"keystone_event": True})
                self._start_adapters()
                return True

            conn.close()
            return False

        except Exception:
            logger.warning("Scheduler lock session lost; will retry.", exc_info=True)
            self._release_lock()
            return False

    def _start_adapters(self):
        """Run each adapter's start hook; a failing hook does not stop scheduling."""
        for adapter in self.adapters:
            try:
                with self.connect() as conn:
                    adapter.on_start(conn)
                    conn.commit()
            except Exception:
                logger.error("Start hook of %s failed.", adapter.job_type, exc_info=True)

    def _release_lock(self):
        conn, self._lock_conn = self._lock_conn, None
        if conn is not None:
            try:
                conn.close()   # closing the session releases the advisory lock
            except Exception:
                pass

    def schedule_once(self):
        """One scheduling pass; returns seconds to sleep until the next slot (max poll)."""
        if not self.holds_scheduler_lock():
            return self.poll_seconds

        try:
            with self.connect() as conn:
                if self.scheduler.tick(conn):
                    self.pool.wake()
        except Exception:
            logger.error("Scheduling pass failed.", exc_info=True)
            return self.poll_seconds

        next_wake = self.scheduler.next_wake_at
        if next_wake is None:
            return self.poll_seconds
        seconds = (next_wake - self.clock()).total_seconds() + MIN_SLEEP_SECONDS
        return min(max(seconds, MIN_SLEEP_SECONDS), self.poll_seconds)

    def _scheduler_loop(self):
        try:
            while not self.stop_event.is_set():
                self.stop_event.wait(self.schedule_once())
        finally:
            self._release_lock()

    def run_forever(self):
        logger.info("Keystone Agent started (max %s workers, poll %s s).",
                    self.pool.max_workers, self.poll_seconds,
                    extra={"keystone_event": True})
        scheduler_thread = threading.Thread(target=self._scheduler_loop,
                                            name="keystone-scheduler", daemon=True)
        scheduler_thread.start()
        try:
            self.pool.run(self.stop_event, self.poll_seconds)
        finally:
            self.stop_event.set()
            scheduler_thread.join(timeout=30)
            for adapter in self.adapters:
                adapter.shutdown()
            logger.info("Keystone Agent stopped.", extra={"keystone_event": True})

    def stop(self, *_):
        self.stop_event.set()
        self.pool.wake()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m repository.agent.agent",
        description="Keystone Agent: scheduler and worker service.",
    )
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS,
                        help=f"tasks running in parallel (default: {DEFAULT_MAX_WORKERS})")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS,
                        help=f"max seconds between queue checks (default: {DEFAULT_POLL_SECONDS})")
    args = parser.parse_args(argv)
    if args.max_workers < 1:
        parser.error("--max-workers must be at least 1")
    return args


def main(argv=None):
    args = parse_args(argv)
    configure_logging("agent", connect=worker.connect_repository)

    pool = WorkerPool(
        connect=worker.connect_repository,
        worker_id=f"agent-{uuid.uuid4()}",
        max_workers=args.max_workers,
    )
    agent = Agent(
        connect=worker.connect_repository,
        adapters=SCHEDULED_JOB_TYPES,
        pool=pool,
        poll_seconds=args.poll_seconds,
    )

    # Ctrl+C, systemd stop and Windows service stop end the loop cleanly.
    signal.signal(signal.SIGINT, agent.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, agent.stop)

    agent.run_forever()


if __name__ == "__main__":
    main()
