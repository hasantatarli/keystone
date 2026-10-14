/*
===============================================================================
Migration No : 025
Version      : V025
Title        : Agent Concurrency And Schedule Lag

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds target.max_concurrent_tasks (per-target limit on parallel collection
tasks) and collector_run_history.scheduled_at (planned start time, so the
delay between plan and actual start can be measured). Implements ADR-0015.
===============================================================================
*/


/*
Design notes (ADR-0015)
-----------------------
The agent runs collection tasks in parallel with a global slot limit
(agent parameter). Every task opens a connection to the monitored database,
so a second, per-target limit protects the customer system: tasks of the
same target wait for a free slot, tasks of different targets run in
parallel.

Schedule lag (started_at - scheduled_at) is the signal for adding agents:
when it keeps growing, the available slots are not enough.
===============================================================================
*/

ALTER TABLE keystone.target
    ADD COLUMN max_concurrent_tasks SMALLINT NOT NULL DEFAULT 3;

ALTER TABLE keystone.target
    ADD CONSTRAINT ck_target_max_concurrent_tasks
        CHECK (max_concurrent_tasks BETWEEN 1 AND 50);

COMMENT ON COLUMN keystone.target.max_concurrent_tasks IS
'Maximum number of collection tasks that may run at the same time against this target.';


ALTER TABLE keystone.collector_run_history
    ADD COLUMN scheduled_at TIMESTAMPTZ;

COMMENT ON COLUMN keystone.collector_run_history.scheduled_at IS
'Planned start time of the task (queue scheduled_at); NULL for runs recorded before V025.';
