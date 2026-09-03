/*
===============================================================================
Migration No : 010
Version      : V010
Title        : Add Retry Exhausted Queue Status

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Extends collection_queue status values with RETRY_EXHAUSTED.

RETRY_EXHAUSTED represents a task that reached the configured retry limit
after repeated stale execution attempts and will no longer be automatically
returned to WAITING.
===============================================================================
*/

ALTER TABLE keystone.collection_queue
DROP CONSTRAINT ck_collection_queue_status;

ALTER TABLE keystone.collection_queue
ADD CONSTRAINT ck_collection_queue_status
CHECK (
    status IN (
        'WAITING',
        'RUNNING',
        'RETRY_EXHAUSTED'
    )
);