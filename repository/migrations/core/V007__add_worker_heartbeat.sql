/*
===============================================================================
Migration No : 007
Version      : V007
Title        : Add Worker Heartbeat Tracking

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Adds worker ownership and heartbeat tracking fields to collection_queue.

worker_id identifies the worker that claimed a task.
heartbeat_at stores the last known heartbeat time of the worker while the
task is in RUNNING state.

These fields will be used to distinguish actively running tasks from stale
tasks left behind by an unavailable or terminated worker.
===============================================================================
*/

ALTER TABLE keystone.collection_queue
ADD COLUMN worker_id varchar(100);

ALTER TABLE keystone.collection_queue
ADD COLUMN heartbeat_at timestamptz;