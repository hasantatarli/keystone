/*
===============================================================================
Migration No : 011
Version      : V011
Title        : Add Collector Failure History Statuses

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Extends collector_run_history status values with TIMEOUT and
CONNECTION_FAILED.

TIMEOUT represents a collector execution cancelled because it exceeded the
configured execution timeout.

CONNECTION_FAILED represents an execution attempt that could not establish
or maintain a connection to the target database.
===============================================================================
*/

ALTER TABLE keystone.collector_run_history
DROP CONSTRAINT ck_collector_run_history_status;

ALTER TABLE keystone.collector_run_history
ADD CONSTRAINT ck_collector_run_history_status
CHECK (
    status IN (
        'SUCCESS',
        'FAILED',
        'STALE',
        'TIMEOUT',
        'CONNECTION_FAILED'
    )
);