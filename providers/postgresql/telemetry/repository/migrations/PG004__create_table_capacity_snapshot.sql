/*
===============================================================================
Migration No : 004
Version      : PG004
Title        : Create PostgreSQL Table Capacity Snapshot

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Creates the PostgreSQL logical table capacity snapshot table.
Stores table size, index size, TOAST size, partition count, logical index count,
estimated rows and tablespace summary for historical capacity tracking.
===============================================================================
*/

CREATE TABLE postgresql.table_capacity_snapshot
(
    target_id              BIGINT        NOT NULL,
    captured_at            TIMESTAMPTZ   NOT NULL,

    database_oid           OID           NOT NULL,
    database_name          VARCHAR(128)  NOT NULL,

    schema_name            VARCHAR(128)  NOT NULL,
    table_oid              OID           NOT NULL,
    table_name             VARCHAR(128)  NOT NULL,

    is_partitioned         BOOLEAN       NOT NULL,
    partition_count        INTEGER       NOT NULL,

    tablespace_names       TEXT          NULL,

    table_size_bytes       BIGINT        NOT NULL,
    indexes_size_bytes     BIGINT        NOT NULL,
    toast_size_bytes       BIGINT        NOT NULL,
    total_size_bytes       BIGINT        NOT NULL,

    estimated_rows         BIGINT        NULL,
    index_count            INTEGER       NOT NULL,

    CONSTRAINT pk_table_capacity_snapshot
        PRIMARY KEY
        (
            target_id,
            captured_at,
            database_oid,
            table_oid
        ),

    CONSTRAINT fk_table_capacity_snapshot_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target(target_id)
);

CREATE INDEX ix_table_capacity_snapshot_history
    ON postgresql.table_capacity_snapshot
    (
        target_id,
        database_oid,
        table_oid,
        captured_at DESC
    );