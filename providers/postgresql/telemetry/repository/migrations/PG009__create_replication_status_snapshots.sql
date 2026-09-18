/*
===============================================================================
Migration No : 009
Version      : PG009
Title        : Create Replication Status Snapshots

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Creates repository tables for PostgreSQL system-level replication status
and connected replica telemetry.
===============================================================================
*/

CREATE TABLE postgresql.replication_status_snapshot
(
    snapshot_id              BIGSERIAL PRIMARY KEY,
    target_id                BIGINT      NOT NULL,
    captured_at              TIMESTAMPTZ NOT NULL,
    current_wal_lsn          PG_LSN      NOT NULL,
    connected_replica_count  BIGINT      NOT NULL
);

CREATE INDEX ix_replication_status_snapshot_target_captured
    ON postgresql.replication_status_snapshot
    (target_id, captured_at DESC);


CREATE TABLE postgresql.replica_status_snapshot
(
    snapshot_id       BIGSERIAL PRIMARY KEY,
    target_id         BIGINT      NOT NULL,
    captured_at       TIMESTAMPTZ NOT NULL,

    application_name  TEXT,
    client_addr       INET,
    client_port       INTEGER,
    backend_start     TIMESTAMPTZ,

    state             TEXT,
    sync_state        TEXT,

    sent_lsn          PG_LSN,
    write_lsn         PG_LSN,
    flush_lsn         PG_LSN,
    replay_lsn        PG_LSN,

    write_lag         INTERVAL,
    flush_lag         INTERVAL,
    replay_lag        INTERVAL,

    reply_time        TIMESTAMPTZ,
    backend_xmin      XID,

    current_wal_lsn   PG_LSN NOT NULL
);

CREATE INDEX ix_replica_status_snapshot_target_captured
    ON postgresql.replica_status_snapshot
    (target_id, captured_at DESC);