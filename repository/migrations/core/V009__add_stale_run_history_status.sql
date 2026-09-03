/*
===============================================================================
Migration No : 009
Version      : V009
Title        : Add Stale Collector Run History Status

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Extends collector_run_history status values with STALE.

STALE represents an execution attempt whose worker stopped providing
heartbeats and whose task was subsequently recovered for another attempt.
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
        'STALE'
    )
);