"""Continuous worker pool (ADR-0015): a freed slot claims the next task at once."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from repository.common.logging_config import get_logger
from repository.worker import worker


logger = get_logger("pool")

DEFAULT_MAX_WORKERS = 20
DEFAULT_LAG_WARNING_SECONDS = 30
RECOVER_EVERY_SECONDS = 30
LAG_WARNING_EVERY_SECONDS = 60


class WorkerPool:
    """Runs claimed tasks in up to max_workers threads; per-target limits apply in the claim."""

    def __init__(self, connect, worker_id, max_workers=DEFAULT_MAX_WORKERS,
                 claim=None, process=None, recover=None,
                 lag_warning_seconds=DEFAULT_LAG_WARNING_SECONDS,
                 monotonic=time.monotonic):
        self.connect = connect
        self.worker_id = worker_id
        self.max_workers = max_workers
        self.claim = claim or worker.claim_tasks
        self.process = process or worker.process_task
        self.recover = recover or worker.recover_stale_tasks
        self.lag_warning_seconds = lag_warning_seconds
        self.monotonic = monotonic

        self.executor = ThreadPoolExecutor(max_workers=max_workers,
                                           thread_name_prefix="keystone-task")
        self._running = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._last_recover = None
        self._last_lag_warning = None

    @property
    def running_count(self):
        with self._lock:
            return len(self._running)

    def wake(self):
        """Ask the pool to look at the queue now (new task queued or slot freed)."""
        self._wake.set()

    def fill(self):
        """Claim as many tasks as there are free slots; returns the number started."""
        free = self.max_workers - self.running_count
        if free <= 0:
            return 0

        with self.connect() as conn:
            tasks = self.claim(conn, worker_id=self.worker_id, limit=free)

        for task in tasks:
            self._check_lag(task)
            future = self.executor.submit(self.process, task)
            with self._lock:
                self._running.add(future)
            future.add_done_callback(lambda f, t=task: self._finished(f, t))

        if tasks:
            logger.info("%s task(s) started; %s running.", len(tasks), self.running_count)
        return len(tasks)

    def _finished(self, future, task):
        with self._lock:
            self._running.discard(future)
        exc = future.exception()
        if exc is not None:
            logger.error(
                "Task %s (%s) failed: %s", task.get("task_id"),
                task.get("collector_key"), exc,
                extra={"context": {"task_id": task.get("task_id"),
                                   "assignment_id": task.get("assignment_id")}},
            )
        self.wake()

    def _check_lag(self, task):
        """Warn (throttled) when tasks start well after their planned time."""
        scheduled, started = task.get("scheduled_at"), task.get("started_at")
        if scheduled is None or started is None:
            return
        lag = (started - scheduled).total_seconds()
        if lag <= self.lag_warning_seconds:
            return

        now = self.monotonic()
        if (self._last_lag_warning is not None
                and now - self._last_lag_warning < LAG_WARNING_EVERY_SECONDS):
            return
        self._last_lag_warning = now
        logger.warning(
            "Task %s started %.0f s after its planned time; worker slots may be insufficient.",
            task.get("task_id"), lag,
            extra={"context": {"task_id": task.get("task_id"),
                               "assignment_id": task.get("assignment_id"),
                               "lag_seconds": round(lag)}},
        )

    def recover_if_due(self):
        """Return tasks of dead workers to the queue, at most every RECOVER_EVERY_SECONDS."""
        now = self.monotonic()
        if self._last_recover is not None and now - self._last_recover < RECOVER_EVERY_SECONDS:
            return
        self._last_recover = now

        with self.connect() as conn:
            recovered = self.recover(conn)
        for task in recovered or []:
            logger.warning("Stale task %s -> %s (retry %s).", task["task_id"],
                           task["status"], task["retry_count"])

    def run(self, stop_event, poll_seconds):
        """Loop until stop_event: recover, fill free slots, wait for a wake-up or poll."""
        try:
            while not stop_event.is_set():
                try:
                    self.recover_if_due()
                    self.fill()
                except Exception:
                    logger.error("Worker pool pass failed.", exc_info=True)
                self._wake.wait(poll_seconds)
                self._wake.clear()
        finally:
            running = self.running_count
            if running:
                logger.info("Waiting for %s running task(s) to finish.", running)
            self.executor.shutdown(wait=True)
