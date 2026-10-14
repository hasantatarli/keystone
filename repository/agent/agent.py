"""Keystone Agent (ADR-0015): long-running service that schedules jobs and runs the worker.

Like SQL Server Agent it runs independently of any user interface; run it under
systemd or as a Windows service. All state lives in the repository, so a
restart continues where it stopped.

    python -m repository.agent.agent [--poll-seconds 10]
"""

import argparse
import signal
import threading
import uuid

from repository.agent.jobs import SCHEDULED_JOB_TYPES
from repository.agent.scheduler import Scheduler, try_acquire_scheduler_lock
from repository.common.logging_config import configure_logging, get_logger
from repository.worker import worker


logger = get_logger("agent")

DEFAULT_POLL_SECONDS = 10


class Agent:
    """One cycle = schedule due jobs (if we hold the scheduler lock) + drain the queue."""

    def __init__(self, connect, adapters, run_worker, poll_seconds=DEFAULT_POLL_SECONDS,
                 clock=None):
        self.connect = connect
        self.scheduler = Scheduler(adapters, clock=clock)
        self.run_worker = run_worker
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
                return True

            conn.close()
            return False

        except Exception:
            logger.warning("Scheduler lock session lost; will retry.", exc_info=True)
            self._release_lock()
            return False

    def _release_lock(self):
        conn, self._lock_conn = self._lock_conn, None
        if conn is not None:
            try:
                conn.close()   # closing the session releases the advisory lock
            except Exception:
                pass

    def run_cycle(self):
        """Schedule (only the lock holder), then run queued work; errors never stop the agent."""
        if self.holds_scheduler_lock():
            try:
                with self.connect() as conn:
                    self.scheduler.tick(conn)
            except Exception:
                logger.error("Scheduling pass failed.", exc_info=True)

        try:
            self.run_worker()
        except Exception:
            logger.error("Worker pass failed.", exc_info=True)

    def run_forever(self):
        logger.info("Keystone Agent started (poll every %s s).", self.poll_seconds,
                    extra={"keystone_event": True})
        try:
            while not self.stop_event.is_set():
                self.run_cycle()
                self.stop_event.wait(self.poll_seconds)
        finally:
            self._release_lock()
            logger.info("Keystone Agent stopped.", extra={"keystone_event": True})

    def stop(self, *_):
        self.stop_event.set()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m repository.agent.agent",
        description="Keystone Agent: scheduler and worker service.",
    )
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS,
                        help=f"seconds between cycles (default: {DEFAULT_POLL_SECONDS})")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    configure_logging("agent", connect=worker.connect_repository)

    worker_id = f"agent-{uuid.uuid4()}"
    agent = Agent(
        connect=worker.connect_repository,
        adapters=SCHEDULED_JOB_TYPES,
        run_worker=lambda: worker.run_once(worker_id=worker_id, quiet_when_idle=True),
        poll_seconds=args.poll_seconds,
    )

    # Ctrl+C, systemd stop and Windows service stop end the loop cleanly.
    signal.signal(signal.SIGINT, agent.stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, agent.stop)

    agent.run_forever()


if __name__ == "__main__":
    main()
