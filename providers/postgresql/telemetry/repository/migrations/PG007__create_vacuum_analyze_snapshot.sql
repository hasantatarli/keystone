/*
===============================================================================
Migration No : 007
Version      : PG007
Title        : Create Vacuum Analyze Snapshot

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Creates the repository table for historical PostgreSQL vacuum and analyze
statistics collected at database and relation level.
===============================================================================
*/

CREATE TABLE postgresql.vacuum_analyze_snapshot
(
    snapshot_id            BIGSERIAL PRIMARY KEY,
    target_id              BIGINT NOT NULL,
    captured_at            TIMESTAMPTZ NOT NULL,

    database_oid           OID NOT NULL,
    database_name          TEXT NOT NULL,

    schema_name            TEXT NOT NULL,
    object_oid             OID NOT NULL,
    object_name            TEXT NOT NULL,
    is_partition           BOOLEAN NOT NULL,

    n_live_tup             BIGINT,
    n_dead_tup             BIGINT,
    n_mod_since_analyze    BIGINT,
    n_ins_since_vacuum     BIGINT,

    last_vacuum            TIMESTAMPTZ,
    last_autovacuum        TIMESTAMPTZ,
    last_analyze           TIMESTAMPTZ,
    last_autoanalyze       TIMESTAMPTZ,

    vacuum_count           BIGINT,
    autovacuum_count       BIGINT,
    analyze_count          BIGINT,
    autoanalyze_count      BIGINT
);

CREATE INDEX ix_vacuum_analyze_snapshot_target_captured
    ON postgresql.vacuum_analyze_snapshot
       (target_id, captured_at DESC);