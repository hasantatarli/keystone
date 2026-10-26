/*
===============================================================================
Migration No    : 015
Version         : PG015
Title           : WAL Status and Prepared Transaction Snapshots

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : NODE / SYSTEM

Description
-----------
Creates repository tables for PG_WAL_STATUS (per node: WAL archiver statistics,
current timeline and when it began) and PG_PREPARED_TRANSACTIONS (per system:
one status row and one row per prepared transaction).
===============================================================================
*/

CREATE TABLE postgresql.wal_status_snapshot
(
    snapshot_id            BIGSERIAL PRIMARY KEY,
    target_id              BIGINT      NOT NULL,
    captured_at            TIMESTAMPTZ NOT NULL,

    in_recovery            BOOLEAN     NOT NULL,
    archive_mode           TEXT        NOT NULL,

    timeline_id            INTEGER,
    timeline_history_file  TEXT,
    timeline_started_at    TIMESTAMPTZ,

    archived_count         BIGINT,
    last_archived_wal      TEXT,
    last_archived_time     TIMESTAMPTZ,
    failed_count           BIGINT,
    last_failed_wal        TEXT,
    last_failed_time       TIMESTAMPTZ,
    stats_reset            TIMESTAMPTZ
);

COMMENT ON COLUMN postgresql.wal_status_snapshot.timeline_id IS
'Current timeline of a primary (from its current WAL file name); NULL on a replica.';

COMMENT ON COLUMN postgresql.wal_status_snapshot.timeline_started_at IS
'Modification time of the current timeline''s history file in pg_wal: when this primary was promoted. NULL on timeline 1 or when the file is missing.';

CREATE INDEX ix_wal_status_snapshot_target_captured
    ON postgresql.wal_status_snapshot
    (target_id, captured_at DESC);


CREATE TABLE postgresql.prepared_transaction_status_snapshot
(
    snapshot_id                BIGSERIAL PRIMARY KEY,
    target_id                  BIGINT      NOT NULL,
    captured_at                TIMESTAMPTZ NOT NULL,
    max_prepared_transactions  INTEGER     NOT NULL,
    prepared_count             BIGINT      NOT NULL
);

CREATE INDEX ix_prepared_transaction_status_snapshot_target_captured
    ON postgresql.prepared_transaction_status_snapshot
    (target_id, captured_at DESC);


CREATE TABLE postgresql.prepared_transaction_snapshot
(
    snapshot_id     BIGSERIAL PRIMARY KEY,
    target_id       BIGINT      NOT NULL,
    captured_at     TIMESTAMPTZ NOT NULL,

    transaction_id  XID         NOT NULL,
    gid             TEXT        NOT NULL,
    prepared_at     TIMESTAMPTZ NOT NULL,
    owner           TEXT,
    database_name   TEXT
);

CREATE INDEX ix_prepared_transaction_snapshot_target_captured
    ON postgresql.prepared_transaction_snapshot
    (target_id, captured_at DESC);
