/*
===============================================================================
Migration No    : 025
Version         : PG025
Title           : Table Access and Lock Waits

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Creates the repository table of PG_TABLE_ACCESS (sequential and index scans,
live rows and size per table, with the database's statistics reset time) and
adds to activity_snapshot the sessions blocking a session that waits on a
lock and when that wait began (pg_locks.waitstart, PostgreSQL 14 and later).
===============================================================================
*/

CREATE TABLE postgresql.table_access_snapshot
(
    snapshot_id       BIGSERIAL PRIMARY KEY,
    target_id         BIGINT      NOT NULL,
    captured_at       TIMESTAMPTZ NOT NULL,
    record_type       TEXT        NOT NULL,       -- DATABASE | TABLE
    database_name     TEXT        NOT NULL,
    schema_name       TEXT,
    object_oid        OID,
    object_name       TEXT,
    seq_scan          BIGINT,
    seq_tup_read      BIGINT,
    idx_scan          BIGINT,
    n_live_tup        BIGINT,
    table_size_bytes  BIGINT,
    stats_reset       TIMESTAMPTZ,

    CONSTRAINT ck_table_access_snapshot_record_type
        CHECK (record_type IN ('DATABASE', 'TABLE'))
);

COMMENT ON TABLE postgresql.table_access_snapshot IS
'pg_stat_user_tables scan counters per table since the database''s stats_reset (NULL: never reset).';

CREATE INDEX ix_table_access_snapshot_target_captured
    ON postgresql.table_access_snapshot
    (target_id, database_name, captured_at DESC);

ALTER TABLE postgresql.activity_snapshot
    ADD COLUMN IF NOT EXISTS blocked_by       INTEGER[],
    ADD COLUMN IF NOT EXISTS lock_wait_start  TIMESTAMPTZ;

COMMENT ON COLUMN postgresql.activity_snapshot.blocked_by IS
'pg_blocking_pids() of a session waiting on a lock; NULL otherwise.';
COMMENT ON COLUMN postgresql.activity_snapshot.lock_wait_start IS
'pg_locks.waitstart of the session''s ungranted lock (PostgreSQL 14+); NULL before 14 or when not waiting.';
