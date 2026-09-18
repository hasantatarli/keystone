/*
===============================================================================
Migration No : 010
Version      : PG010
Title        : Create Replication Slot Snapshot

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Creates the repository table for PostgreSQL physical and logical replication
slot telemetry.
===============================================================================
*/

CREATE TABLE postgresql.replication_slot_snapshot
(
    snapshot_id          BIGSERIAL PRIMARY KEY,
    target_id            BIGINT      NOT NULL,
    captured_at          TIMESTAMPTZ NOT NULL,

    slot_name            TEXT        NOT NULL,
    plugin               TEXT,
    slot_type            TEXT        NOT NULL,
    database_name        TEXT,

    temporary            BOOLEAN     NOT NULL,
    active               BOOLEAN     NOT NULL,
    active_pid           INTEGER,

    slot_xmin            XID,
    catalog_xmin         XID,

    restart_lsn          PG_LSN,
    confirmed_flush_lsn  PG_LSN,

    wal_status           TEXT,
    safe_wal_size        BIGINT,

    two_phase            BOOLEAN     NOT NULL,
    conflicting          BOOLEAN,
    invalidation_reason  TEXT,
    failover             BOOLEAN     NOT NULL
);

CREATE INDEX ix_replication_slot_snapshot_target_captured
    ON postgresql.replication_slot_snapshot
    (target_id, captured_at DESC);