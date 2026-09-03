/*
===============================================================================
Migration No : 003
Version      : PG003
Title        : Create PostgreSQL Database Snapshot

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Creates the PostgreSQL database snapshot table.

The table stores historical database inventory and capacity information for
a PostgreSQL system target. For clustered PostgreSQL environments, the logical
cluster is represented as a SYSTEM target and database information is collected
once from the primary-facing connection.

Historical snapshots support database growth analysis and configuration change
tracking without duplicating the same logical database information per node.
===============================================================================
*/

CREATE TABLE postgresql.database_snapshot
(
    target_id              BIGINT        NOT NULL,
    captured_at            TIMESTAMPTZ   NOT NULL,

    database_oid           OID           NOT NULL,
    database_name          VARCHAR(128)  NOT NULL,
    database_owner         VARCHAR(128)  NULL,

    encoding               VARCHAR(64)   NULL,
    collation_name              VARCHAR(128)  NULL,
    ctype_name                  VARCHAR(128)  NULL,

    connection_limit       INTEGER       NULL,
    allow_connections      BOOLEAN       NULL,
    is_template            BOOLEAN       NULL,

    database_size_bytes    BIGINT        NULL,
    tablespace_name        VARCHAR(128)  NULL,

    CONSTRAINT pk_database_snapshot
        PRIMARY KEY
        (
            target_id,
            captured_at,
            database_oid
        ),

    CONSTRAINT fk_database_snapshot_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target(target_id)
);


CREATE INDEX ix_database_snapshot_history
    ON postgresql.database_snapshot
    (
        target_id,
        database_oid,
        captured_at DESC
    );