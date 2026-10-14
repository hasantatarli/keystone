"""Job adapters for the scheduler (ADR-0015). One adapter per job type."""

from concurrent.futures import ThreadPoolExecutor
import threading

from repository.agent.scheduler import JobAdapter, ScheduledItem
from repository.common.logging_config import get_logger
from repository.intelligence import assessment_engine


logger = get_logger("jobs")

ASSESSMENT_WORKERS = 2
# A RUNNING assessment run older than this was abandoned (assessments take seconds).
ABANDONED_ASSESSMENT_SECONDS = 3600


class CollectorJobs(JobAdapter):
    """SCHEDULED collector assignments; running one means queueing it for the worker."""

    job_type = "COLLECTOR"

    def list_items(self, conn):
        # Last run from history; busy = already WAITING/RUNNING
        # (the queue allows one active task per assignment).
        rows = conn.execute(
            """
            SELECT
                ca.assignment_id,
                ca.interval_seconds,
                last_run.started_at AS last_started_at,
                last_run.finished_at AS last_finished_at,
                EXISTS (
                    SELECT 1
                    FROM keystone.collection_queue q
                    WHERE q.assignment_id = ca.assignment_id
                      AND q.status IN ('WAITING', 'RUNNING')
                ) AS is_busy
            FROM keystone.collector_assignment ca
            JOIN keystone.collector_definition cd
                ON cd.collector_id = ca.collector_id
            JOIN keystone.target t
                ON t.target_id = ca.target_id
            LEFT JOIN LATERAL (
                SELECT rh.started_at, rh.finished_at
                FROM keystone.collector_run_history rh
                WHERE rh.assignment_id = ca.assignment_id
                ORDER BY rh.started_at DESC
                LIMIT 1
            ) last_run ON TRUE
            WHERE ca.execution_mode = 'SCHEDULED'
              AND ca.is_enabled
              AND cd.is_active
              AND t.is_active
            ORDER BY ca.assignment_id
            """
        ).fetchall()

        return [
            ScheduledItem(
                job_type=self.job_type,
                key=(_value(row, "assignment_id", 0),),
                interval_seconds=_value(row, "interval_seconds", 1),
                last_started_at=_value(row, "last_started_at", 2),
                last_finished_at=_value(row, "last_finished_at", 3),
                is_busy=_value(row, "is_busy", 4),
            )
            for row in rows
        ]

    def run(self, conn, item, planned_at):
        # scheduled_at = planned slot, so start lag can be measured.
        # ON CONFLICT: a task queued meanwhile (e.g. manually) is not duplicated.
        conn.execute(
            """
            INSERT INTO keystone.collection_queue
                (assignment_id, status, scheduled_at)
            VALUES (%s, 'WAITING', %s)
            ON CONFLICT DO NOTHING
            """,
            (item.key[0], planned_at),
        )


class AssessmentJobs(JobAdapter):
    """Assessment schedules; runs read only the repository, in a small pool of their own."""

    job_type = "ASSESSMENT"

    def __init__(self, connect=None, run_assessment=None, workers=ASSESSMENT_WORKERS):
        self.connect = connect or assessment_engine.connect_repository
        self.run_assessment = run_assessment or assessment_engine.run_assessment
        self.workers = workers
        self._executor = None
        self._running = set()
        self._lock = threading.Lock()

    def on_start(self, conn):
        # Runs left RUNNING by a stopped agent, then configuration warnings.
        abandoned = conn.execute(
            """
            UPDATE keystone.assessment_run
            SET status = 'FAILED',
                finished_at = clock_timestamp(),
                status_message = 'Abandoned: the run did not finish (agent stopped).'
            WHERE status = 'RUNNING'
              AND started_at < clock_timestamp() - (%s * INTERVAL '1 second')
            RETURNING assessment_run_id
            """,
            (ABANDONED_ASSESSMENT_SECONDS,),
        ).fetchall()
        for row in abandoned:
            logger.warning("Assessment run %s marked FAILED (abandoned).",
                           _value(row, "assessment_run_id", 0))

        for row in conn.execute(
            """
            SELECT target_name, assessment_key, rule_key, problem, detail
            FROM keystone.schedule_consistency_warning
            ORDER BY target_name, assessment_key, rule_key
            """
        ).fetchall():
            logger.warning(
                "Schedule warning on %s: %s %s %s - %s",
                *(_value(row, name, i) for i, name in enumerate(
                    ("target_name", "assessment_key", "rule_key", "problem", "detail"))),
            )

    def list_items(self, conn):
        rows = conn.execute(
            """
            SELECT
                ad.assessment_key,
                s.target_id,
                s.interval_seconds,
                s.offset_seconds,
                last_run.started_at AS last_started_at,
                last_run.finished_at AS last_finished_at,
                COALESCE(last_run.status = 'RUNNING', FALSE) AS is_running
            FROM keystone.assessment_schedule s
            JOIN keystone.assessment_definition ad
                ON ad.assessment_id = s.assessment_id
            JOIN keystone.target t
                ON t.target_id = s.target_id
            LEFT JOIN LATERAL (
                SELECT ar.started_at, ar.finished_at, ar.status
                FROM keystone.assessment_run ar
                WHERE ar.assessment_id = s.assessment_id
                  AND ar.target_id = s.target_id
                ORDER BY ar.started_at DESC
                LIMIT 1
            ) last_run ON TRUE
            WHERE s.is_enabled
              AND ad.is_enabled
              AND t.is_active
            ORDER BY s.schedule_id
            """
        ).fetchall()

        items = []
        for row in rows:
            key = (_value(row, "assessment_key", 0), _value(row, "target_id", 1))
            with self._lock:
                busy = key in self._running or _value(row, "is_running", 6)
            items.append(ScheduledItem(
                job_type=self.job_type,
                key=key,
                interval_seconds=_value(row, "interval_seconds", 2),
                offset_seconds=_value(row, "offset_seconds", 3),
                catch_up=False,         # evidence of this slot is not collected yet
                last_started_at=_value(row, "last_started_at", 4),
                last_finished_at=_value(row, "last_finished_at", 5),
                is_busy=busy,
            ))
        return items

    def run(self, conn, item, planned_at):
        # Submitted, not run here: the scheduler thread never waits for an assessment.
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.workers,
                                                thread_name_prefix="keystone-assessment")
        with self._lock:
            self._running.add(item.key)
        self._executor.submit(self._execute, item, planned_at)

    def _execute(self, item, planned_at):
        assessment_key, target_id = item.key
        try:
            with self.connect() as conn:
                self.run_assessment(conn, assessment_key, target_id,
                                    scheduled_at=planned_at)
        except Exception:
            logger.error("Scheduled assessment %s for target %s failed.",
                         assessment_key, target_id, exc_info=True,
                         extra={"context": {"assessment_key": assessment_key,
                                            "target_id": target_id}})
        finally:
            with self._lock:
                self._running.discard(item.key)

    def shutdown(self):
        if self._executor is not None:
            self._executor.shutdown(wait=True)


def _value(row, name, index):
    """Read a column from dict or tuple rows."""
    return row[name] if isinstance(row, dict) else row[index]


# Job types the agent schedules. A new timed job type = a new adapter here.
SCHEDULED_JOB_TYPES = [
    CollectorJobs(),
    AssessmentJobs(),
]
