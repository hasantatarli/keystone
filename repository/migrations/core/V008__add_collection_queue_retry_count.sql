/*
===============================================================================
Migration No : 008
Version      : V008
Title        : Add Collection Queue Retry Count

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Adds retry tracking to collection_queue.

retry_count stores how many times a task has been recovered from a stale
RUNNING state and returned to WAITING for another execution attempt.

The initial execution is not considered a retry, therefore new tasks start
with retry_count = 0.
===============================================================================
*/

ALTER TABLE keystone.collection_queue
ADD COLUMN retry_count integer NOT NULL DEFAULT 0;