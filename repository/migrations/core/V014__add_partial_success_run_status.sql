/*
===============================================================================
Migration No : 014
Version      : V014
Title        : Add Partial Success Run Status

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PARTIAL_SUCCESS as a valid collector run status for database-scoped
collectors where some databases succeed and others fail.
===============================================================================
*/

ALTER TABLE keystone.collector_run_history
    DROP CONSTRAINT ck_collector_run_history_status;

ALTER TABLE keystone.collector_run_history
    ADD CONSTRAINT ck_collector_run_history_status
    CHECK
    (
        status IN
        (
            'SUCCESS',
            'PARTIAL_SUCCESS',
            'FAILED',
            'STALE',
            'TIMEOUT',
            'CONNECTION_FAILED'
        )
    );