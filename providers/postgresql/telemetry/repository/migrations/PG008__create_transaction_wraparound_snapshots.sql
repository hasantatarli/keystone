/*
===============================================================================
Migration No : 008
Version      : PG008
Title        : Create Transaction Wraparound Snapshots

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Creates repository tables for PostgreSQL transaction ID and MultiXact
wraparound telemetry at database and relation level.
===============================================================================
*/

CREATE TABLE postgresql.transaction_wraparound_snapshot
(
    snapshot_id        BIGSERIAL PRIMARY KEY,
    target_id          BIGINT NOT NULL,
    captured_at        TIMESTAMPTZ NOT NULL,

    database_oid       OID NOT NULL,
    database_name      TEXT NOT NULL,

    frozen_xid         XID NOT NULL,
    xid_age            BIGINT NOT NULL,

    min_mxid           XID NOT NULL,
    mxid_age           BIGINT NOT NULL
);

CREATE INDEX ix_transaction_wraparound_snapshot_target_captured
    ON postgresql.transaction_wraparound_snapshot
    (
        target_id,
        captured_at DESC
    );


CREATE TABLE postgresql.relation_wraparound_snapshot
(
    snapshot_id        BIGSERIAL PRIMARY KEY,
    target_id          BIGINT NOT NULL,
    captured_at        TIMESTAMPTZ NOT NULL,

    database_oid       OID NOT NULL,
    database_name      TEXT NOT NULL,

    schema_name        TEXT NOT NULL,
    object_oid         OID NOT NULL,
    object_name        TEXT NOT NULL,
    is_partition       BOOLEAN NOT NULL,

    frozen_xid         XID NOT NULL,
    xid_age            BIGINT NOT NULL,

    min_mxid           XID NOT NULL,
    mxid_age           BIGINT NOT NULL
);

CREATE INDEX ix_relation_wraparound_snapshot_target_captured
    ON postgresql.relation_wraparound_snapshot
    (
        target_id,
        captured_at DESC
    );