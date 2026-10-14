"""Generic interval scheduler (ADR-0015): decides WHEN; job adapters decide WHAT.

Adapters list their scheduled items (with last start/finish taken from their
own history) and run an item. The rules below live only here.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from repository.common.logging_config import get_logger


logger = get_logger("scheduler")

# Session-level advisory lock key: only one active scheduler per repository.
SCHEDULER_LOCK_KEY = 0x4B45595354  # "KEYST"

# A run that starts this late after its slot is a catch-up, planned at "now".
DEFAULT_GRACE_SECONDS = 15


@dataclass(frozen=True)
class ScheduledItem:
    """One schedulable thing, e.g. a collector assignment or assessment schedule."""

    job_type: str
    key: tuple
    interval_seconds: int
    last_started_at: datetime = None          # from the adapter's own history
    last_finished_at: datetime = None         # finish of that same run
    is_busy: bool = False                     # queued or running right now
    offset_seconds: int = 0                   # run this long after each slot
    catch_up: bool = True                     # run once at once when overdue
    payload: dict = field(default_factory=dict, compare=False, hash=False)


class JobAdapter:
    """Contract for a job type: list scheduled items and run one of them."""

    job_type = None

    def list_items(self, conn):
        raise NotImplementedError

    def run(self, conn, item, planned_at):
        raise NotImplementedError

    def on_start(self, conn):
        """Called once when this agent becomes the scheduler (cleanup, checks)."""

    def shutdown(self):
        """Called when the agent stops; wait for work the adapter started itself."""


def slot_start(now, interval_seconds, offset_seconds=0):
    """Start of the fixed time slot containing now (grid anchored to the Unix epoch + offset)."""
    shifted = int(now.timestamp()) - offset_seconds
    start = (shifted // interval_seconds) * interval_seconds + offset_seconds
    return datetime.fromtimestamp(start, tz=timezone.utc)


class Scheduler:
    """Runs due items of all registered adapters once per tick.

    Rules: items run on a fixed grid (every interval, aligned to the clock);
    a slot that began while the previous run was still going is skipped;
    a failed run counts as run; after downtime an item runs once at once
    (no catch-up of every missed slot), unless catch_up is off: then it
    waits for the next slot; an in-memory dispatch time covers
    the case where the run could not be recorded in the repository.
    """

    def __init__(self, adapters, clock=None, grace_seconds=DEFAULT_GRACE_SECONDS):
        self.adapters = list(adapters)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.grace = timedelta(seconds=grace_seconds)
        self.next_wake_at = None
        self._dispatched_at = {}

    def last_run(self, item):
        """(start, finish) of the latest run, from history or in-memory dispatch."""
        dispatched = self._dispatched_at.get((item.job_type, item.key))
        started = item.last_started_at

        if dispatched is not None and (started is None or dispatched > started):
            return dispatched, dispatched      # not recorded yet: finish unknown
        if started is None:
            return None, None
        return started, item.last_finished_at or started

    def is_due(self, item, now):
        if item.is_busy:
            return False
        slot = slot_start(now, item.interval_seconds, item.offset_seconds)
        if not item.catch_up and now - slot > self.grace:
            return False                # no catch-up: wait for the next slot
        started, finished = self.last_run(item)
        if started is None:
            return True
        # Already ran in this slot, or the slot began while the previous run was busy.
        return started < slot and finished <= slot

    def planned_time(self, item, now):
        """The slot start when on time; now for a first run or a late catch-up."""
        slot = slot_start(now, item.interval_seconds, item.offset_seconds)
        started, _ = self.last_run(item)
        if item.catch_up and (started is None or now - slot > self.grace):
            return now
        return slot

    def tick(self, conn):
        """One scheduling pass; returns the items that were dispatched."""
        now = self.clock()
        dispatched = []
        next_wake = None

        for adapter in self.adapters:
            try:
                items = adapter.list_items(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                logger.error(
                    "Could not list %s items", adapter.job_type, exc_info=True
                )
                continue

            for item in items:
                boundary = (slot_start(now, item.interval_seconds, item.offset_seconds)
                            + timedelta(seconds=item.interval_seconds))
                next_wake = boundary if next_wake is None else min(next_wake, boundary)

                if not self.is_due(item, now):
                    continue

                planned_at = self.planned_time(item, now)
                # Recorded before running: a failure must not cause a retry
                # on every tick.
                self._dispatched_at[(item.job_type, item.key)] = now
                try:
                    adapter.run(conn, item, planned_at)
                    conn.commit()
                    dispatched.append(item)
                except Exception:
                    conn.rollback()
                    logger.error(
                        "Scheduled %s %s failed",
                        item.job_type,
                        item.key,
                        exc_info=True,
                        extra={"context": {"job_type": item.job_type,
                                           "key": list(item.key)}},
                    )

        self.next_wake_at = next_wake
        return dispatched


def try_acquire_scheduler_lock(conn):
    """True if this connection now holds the single-scheduler advisory lock."""
    row = conn.execute(
        "SELECT pg_try_advisory_lock(%s) AS acquired", (SCHEDULER_LOCK_KEY,)
    ).fetchone()
    conn.commit()
    return bool(row["acquired"] if isinstance(row, dict) else row[0])
