/*
===============================================================================
Migration No    : 019
Version         : PG019
Title           : Replication Slot Status Snapshot

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Creates the status table for PG_REPLICATION_SLOTS: one row per collection with
the slot count, so a system without replication slots is evidence ("no slots")
instead of missing data. Slot rows stay in replication_slot_snapshot.
===============================================================================
*/

CREATE TABLE postgresql.replication_slot_status_snapshot
(
    snapshot_id  BIGSERIAL PRIMARY KEY,
    target_id    BIGINT      NOT NULL,
    captured_at  TIMESTAMPTZ NOT NULL,
    slot_count   BIGINT      NOT NULL
);

COMMENT ON TABLE postgresql.replication_slot_status_snapshot IS
'One row per PG_REPLICATION_SLOTS collection; slot_count 0 means the system has no replication slots.';

CREATE INDEX ix_replication_slot_status_snapshot_target_captured
    ON postgresql.replication_slot_status_snapshot
    (target_id, captured_at DESC);
