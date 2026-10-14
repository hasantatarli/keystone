"""Generic interval scheduler (ADR-0015): decides WHEN; job adapters decide WHAT.

Adapters list their scheduled items (with last start time taken from their own
history) and run an item. The rules below live only here.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from repository.common.logging_config import get_logger


logger = get_logger("scheduler")

# Session-level advisory lock key: only one active scheduler per repository.
SCHEDULER_LOCK_KEY = 0x4B45595354  # "KEYST"


@dataclass(frozen=True)
class ScheduledItem:
    """One schedulable thing, e.g. a collector assignment or assessment schedule."""

    job_type: str
    key: tuple
    interval_seconds: int
    last_started_at: datetime = None          # from the adapter's own history
    payload: dict = field(default_factory=dict, compare=False, hash=False)


class JobAdapter:
    """Contract for a job type: list scheduled items and run one of them."""

    job_type = None

    def list_items(self, conn):
        raise NotImplementedError

    def run(self, conn, item, now):
        raise NotImplementedError


class Scheduler:
    """Runs due items of all registered adapters once per tick.

    Rules: due when last start + interval <= now; a failed run counts as run;
    overdue items run once (no catch-up); an in-memory dispatch time covers
    the case where the run could not be recorded in the repository.
    """

    def __init__(self, adapters, clock=None):
        self.adapters = list(adapters)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._dispatched_at = {}

    def last_run(self, item):
        """Latest of repository history and our own in-memory dispatch time."""
        candidates = [
            moment for moment in (
                item.last_started_at,
                self._dispatched_at.get((item.job_type, item.key)),
            )
            if moment is not None
        ]
        return max(candidates) if candidates else None

    def is_due(self, item, now):
        last = self.last_run(item)
        return last is None or last + timedelta(seconds=item.interval_seconds) <= now

    def tick(self, conn):
        """One scheduling pass; returns the items that were dispatched."""
        now = self.clock()
        dispatched = []

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
                if not self.is_due(item, now):
                    continue

                # Recorded before running: a failure must not cause a retry
                # on every tick.
                self._dispatched_at[(item.job_type, item.key)] = now
                try:
                    adapter.run(conn, item, now)
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

        return dispatched


def try_acquire_scheduler_lock(conn):
    """True if this connection now holds the single-scheduler advisory lock."""
    row = conn.execute(
        "SELECT pg_try_advisory_lock(%s) AS acquired", (SCHEDULER_LOCK_KEY,)
    ).fetchone()
    conn.commit()
    return bool(row["acquired"] if isinstance(row, dict) else row[0])
