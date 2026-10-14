/*
===============================================================================
Migration No : 027
Version      : V027
Title        : Long Running Task Detection

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds collector_assignment.expected_max_seconds (optional manual threshold for
the long-running task warning) and an index for reading the latest runs of an
assignment from collector_run_history.
===============================================================================
*/


/*
Design notes (DEVELOPMENT_STATUS, hardening, 2026-10-14)
--------------------------------------------------------
A collection task that runs much longer than usual logs one WARNING and is
left for manual check; it is not stopped. The threshold is 3x the median
duration of the assignment's last 20 successful runs (minimum 120 s), or
600 s until 5 successful runs exist. expected_max_seconds replaces the
calculated threshold for assignments whose long runs are known and accepted,
for example during a weekly backup.

The index serves the agent, which reads the latest run of every scheduled
assignment on each scheduling pass, and the median calculation.
===============================================================================
*/

ALTER TABLE keystone.collector_assignment
    ADD COLUMN expected_max_seconds INTEGER;

ALTER TABLE keystone.collector_assignment
    ADD CONSTRAINT ck_collector_assignment_expected_max
        CHECK (expected_max_seconds IS NULL OR expected_max_seconds > 0);

COMMENT ON COLUMN keystone.collector_assignment.expected_max_seconds IS
'Optional: a run longer than this logs a long-running warning; NULL uses 3x the median of recent successful runs.';

CREATE INDEX ix_collector_run_history_assignment_started
    ON keystone.collector_run_history (assignment_id, started_at DESC);
