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

# Long-running warning: 3x median of recent successful runs, at least 2 min;
# 10 min until there is enough history. No task is stopped.
LONG_RUNNING_FACTOR = 3
LONG_RUNNING_MIN_SECONDS = 120
LONG_RUNNING_DEFAULT_SECONDS = 600
LONG_RUNNING_MIN_HISTORY = 5
LONG_RUNNING_HISTORY_RUNS = 20


def long_running_threshold(median_seconds, successful_runs, expected_max_seconds=None):
    """Seconds after which a running task is reported as long-running."""
    if expected_max_seconds:
        return expected_max_seconds
    if successful_runs < LONG_RUNNING_MIN_HISTORY or median_seconds is None:
        return LONG_RUNNING_DEFAULT_SECONDS
    return max(LONG_RUNNING_FACTOR * median_seconds, LONG_RUNNING_MIN_SECONDS)


def load_duration_stats(conn, assignment_ids):
    """{assignment_id: (median_seconds, successful_runs, expected_max_seconds)}."""
    rows = conn.execute(
        """
        SELECT
            ca.assignment_id,
            ca.expected_max_seconds,
            recent.runs,
            recent.median_ms
        FROM keystone.collector_assignment ca
        LEFT JOIN LATERAL (
            SELECT
                count(*) AS runs,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY r.execution_time_ms) AS median_ms
            FROM (
                SELECT rh.execution_time_ms
                FROM keystone.collector_run_history rh
                WHERE rh.assignment_id = ca.assignment_id
                  AND rh.status IN ('SUCCESS', 'PARTIAL_SUCCESS')
                  AND rh.execution_time_ms IS NOT NULL
                ORDER BY rh.started_at DESC
                LIMIT %s
            ) r
        ) recent ON TRUE
        WHERE ca.assignment_id = ANY(%s)
        """,
        (LONG_RUNNING_HISTORY_RUNS, list(assignment_ids)),
    ).fetchall()
    conn.commit()
    return {
        row["assignment_id"]: (
            None if row["median_ms"] is None else row["median_ms"] / 1000.0,
            row["runs"] or 0,
            row["expected_max_seconds"],
        )
        for row in rows
    }


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
        self._running = {}          # future -> (task, monotonic start)
        self._warned_long = set()   # task ids already reported as long-running
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
                self._running[future] = (task, self.monotonic())
            future.add_done_callback(lambda f, t=task: self._finished(f, t))

        if tasks:
            logger.info("%s task(s) started; %s running.", len(tasks), self.running_count)
        return len(tasks)

    def _finished(self, future, task):
        with self._lock:
            self._running.pop(future, None)
            self._warned_long.discard(task.get("task_id"))
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

    def check_long_running(self):
        """Warn once per task that runs much longer than usual; nothing is stopped."""
        now = self.monotonic()
        with self._lock:
            candidates = [
                (task, now - started) for task, started in self._running.values()
                if now - started >= LONG_RUNNING_MIN_SECONDS
                and task.get("task_id") not in self._warned_long
            ]
        if not candidates:
            return

        with self.connect() as conn:
            stats = load_duration_stats(conn, {t["assignment_id"] for t, _ in candidates})

        for task, elapsed in candidates:
            median, runs, expected = stats.get(task["assignment_id"], (None, 0, None))
            threshold = long_running_threshold(median, runs, expected)
            if elapsed <= threshold:
                continue
            with self._lock:
                self._warned_long.add(task.get("task_id"))
            usual = f"usually {median:.0f} s" if median is not None and runs else "no history yet"
            logger.warning(
                "Task %s: %s on %s running for %.0f min (%s, threshold %.0f s); "
                "its next slots are skipped until it ends. Check manually.",
                task.get("task_id"), task.get("collector_key"), task.get("target_name"),
                elapsed / 60, usual, threshold,
                extra={"context": {"task_id": task.get("task_id"),
                                   "assignment_id": task.get("assignment_id"),
                                   "running_seconds": round(elapsed),
                                   "threshold_seconds": round(threshold)}},
            )

    def recover_if_due(self):
        """Every RECOVER_EVERY_SECONDS: requeue tasks of dead workers, report long-running ones."""
        now = self.monotonic()
        if self._last_recover is not None and now - self._last_recover < RECOVER_EVERY_SECONDS:
            return
        self._last_recover = now

        with self.connect() as conn:
            recovered = self.recover(conn)
        for task in recovered or []:
            logger.warning("Stale task %s -> %s (retry %s).", task["task_id"],
                           task["status"], task["retry_count"])

        self.check_long_running()

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
