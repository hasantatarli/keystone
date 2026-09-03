/*
===============================================================================
Migration No : 004
Version      : V004
Title        : Collection Execution Foundation

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Creates the collection execution queue and collector run history structures.

The collection queue stores active and waiting collection tasks.
Completed executions are written to collector_run_history and removed from
the active queue.

Automatic retry is intentionally not implemented. Failed executions are
recorded in history and may later generate alerts or be executed manually.
===============================================================================
*/


/* ============================================================================
   COLLECTION QUEUE
   ============================================================================ */

CREATE TABLE keystone.collection_queue
(
    task_id          BIGINT GENERATED ALWAYS AS IDENTITY,

    assignment_id    BIGINT      NOT NULL,

    status           VARCHAR(20) NOT NULL,
    scheduled_at     TIMESTAMPTZ NOT NULL,
    started_at       TIMESTAMPTZ,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    status_message   TEXT,

    CONSTRAINT pk_collection_queue
        PRIMARY KEY (task_id),

    CONSTRAINT fk_collection_queue_assignment
        FOREIGN KEY (assignment_id)
        REFERENCES keystone.collector_assignment (assignment_id),

    CONSTRAINT ck_collection_queue_status
        CHECK (
            status IN ('WAITING', 'RUNNING')
        )
);


/*
Prevents the same collector assignment from having more than one
active task at the same time.

This protects against duplicate scheduling and overlapping executions.
*/
CREATE UNIQUE INDEX uq_collection_queue_active_assignment
    ON keystone.collection_queue (assignment_id)
    WHERE status IN ('WAITING', 'RUNNING');


COMMENT ON TABLE keystone.collection_queue IS
'Stores collection tasks that are waiting to run or currently running.';

COMMENT ON COLUMN keystone.collection_queue.assignment_id IS
'Collector assignment that will be executed.';

COMMENT ON COLUMN keystone.collection_queue.status IS
'Current queue state. Supported values are WAITING and RUNNING.';

COMMENT ON COLUMN keystone.collection_queue.scheduled_at IS
'Time at which the collection task is eligible to run.';

COMMENT ON COLUMN keystone.collection_queue.started_at IS
'Time at which a worker started processing the task.';

COMMENT ON COLUMN keystone.collection_queue.status_message IS
'Optional runtime information about the queued task.';



/* ============================================================================
   COLLECTOR RUN HISTORY
   ============================================================================ */

CREATE TABLE keystone.collector_run_history
(
    run_id             BIGINT GENERATED ALWAYS AS IDENTITY,

    assignment_id      BIGINT       NOT NULL,

    /*
    task_id is intentionally not a foreign key.

    collection_queue records are removed after execution, while the task_id
    remains here as a correlation identifier for troubleshooting and audit.
    */
    task_id             BIGINT,

    started_at         TIMESTAMPTZ  NOT NULL,
    finished_at        TIMESTAMPTZ  NOT NULL,

    status             VARCHAR(20)  NOT NULL,

    execution_time_ms  BIGINT,
    rows_collected     BIGINT,

    executed_by        VARCHAR(128) NOT NULL,

    status_message     TEXT,
    error_message      TEXT,

    CONSTRAINT pk_collector_run_history
        PRIMARY KEY (run_id),

    CONSTRAINT fk_collector_run_history_assignment
        FOREIGN KEY (assignment_id)
        REFERENCES keystone.collector_assignment (assignment_id),

    CONSTRAINT ck_collector_run_history_status
        CHECK (
            status IN ('SUCCESS', 'FAILED')
        ),

    CONSTRAINT ck_collector_run_history_execution_time
        CHECK (
            execution_time_ms IS NULL
            OR execution_time_ms >= 0
        ),

    CONSTRAINT ck_collector_run_history_rows
        CHECK (
            rows_collected IS NULL
            OR rows_collected >= 0
        ),

    CONSTRAINT ck_collector_run_history_time
        CHECK (
            finished_at >= started_at
        )
);


COMMENT ON TABLE keystone.collector_run_history IS
'Stores completed collector execution history.';

COMMENT ON COLUMN keystone.collector_run_history.assignment_id IS
'Collector assignment that was executed.';

COMMENT ON COLUMN keystone.collector_run_history.task_id IS
'Original queue task identifier retained for correlation and audit.';

COMMENT ON COLUMN keystone.collector_run_history.status IS
'Final execution status. Supported values are SUCCESS and FAILED.';

COMMENT ON COLUMN keystone.collector_run_history.execution_time_ms IS
'Collector execution duration in milliseconds.';

COMMENT ON COLUMN keystone.collector_run_history.rows_collected IS
'Number of rows collected from the target system when available.';

COMMENT ON COLUMN keystone.collector_run_history.executed_by IS
'Worker, process, or execution mechanism that ran the collector.';

COMMENT ON COLUMN keystone.collector_run_history.status_message IS
'General execution result or informational message.';

COMMENT ON COLUMN keystone.collector_run_history.error_message IS
'Technical error details for failed executions.';