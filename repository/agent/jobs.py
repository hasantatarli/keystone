"""Job adapters for the scheduler (ADR-0015). One adapter per job type."""

from repository.agent.scheduler import JobAdapter, ScheduledItem


class CollectorJobs(JobAdapter):
    """SCHEDULED collector assignments; running one means queueing it for the worker."""

    job_type = "COLLECTOR"

    def list_items(self, conn):
        # Last start from run history; assignments already WAITING/RUNNING
        # are skipped (the queue allows one active task per assignment).
        rows = conn.execute(
            """
            SELECT
                ca.assignment_id,
                ca.interval_seconds,
                (
                    SELECT max(rh.started_at)
                    FROM keystone.collector_run_history rh
                    WHERE rh.assignment_id = ca.assignment_id
                ) AS last_started_at
            FROM keystone.collector_assignment ca
            JOIN keystone.collector_definition cd
                ON cd.collector_id = ca.collector_id
            JOIN keystone.target t
                ON t.target_id = ca.target_id
            WHERE ca.execution_mode = 'SCHEDULED'
              AND ca.is_enabled
              AND cd.is_active
              AND t.is_active
              AND NOT EXISTS (
                  SELECT 1
                  FROM keystone.collection_queue q
                  WHERE q.assignment_id = ca.assignment_id
                    AND q.status IN ('WAITING', 'RUNNING')
              )
            ORDER BY ca.assignment_id
            """
        ).fetchall()

        return [
            ScheduledItem(
                job_type=self.job_type,
                key=(_value(row, "assignment_id", 0),),
                interval_seconds=_value(row, "interval_seconds", 1),
                last_started_at=_value(row, "last_started_at", 2),
            )
            for row in rows
        ]

    def run(self, conn, item, now):
        # ON CONFLICT: a task queued meanwhile (e.g. manually) is not duplicated.
        conn.execute(
            """
            INSERT INTO keystone.collection_queue
                (assignment_id, status, scheduled_at)
            VALUES (%s, 'WAITING', clock_timestamp())
            ON CONFLICT DO NOTHING
            """,
            (item.key[0],),
        )


def _value(row, name, index):
    """Read a column from dict or tuple rows."""
    return row[name] if isinstance(row, dict) else row[index]


# Job types the agent schedules. A new timed job type = a new adapter here.
SCHEDULED_JOB_TYPES = [
    CollectorJobs(),
]
