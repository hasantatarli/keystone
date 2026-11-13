/*
===============================================================================
Migration No    : 024
Version         : PG024
Title           : Database Statistics Snapshot

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Creates the repository table for PG_DATABASE_STATS: cumulative counters of
pg_stat_database per database (transactions, blocks read and hit, temporary
files and bytes) with their reset time.
===============================================================================
*/

CREATE TABLE postgresql.database_stats_snapshot
(
    snapshot_id    BIGSERIAL PRIMARY KEY,
    target_id      BIGINT      NOT NULL,
    captured_at    TIMESTAMPTZ NOT NULL,
    database_name  TEXT        NOT NULL,
    xact_commit    BIGINT,
    xact_rollback  BIGINT,
    blks_read      BIGINT,
    blks_hit       BIGINT,
    temp_files     BIGINT,
    temp_bytes     BIGINT,
    stats_reset    TIMESTAMPTZ,
    in_recovery    BOOLEAN     NOT NULL
);

COMMENT ON TABLE postgresql.database_stats_snapshot IS
'pg_stat_database counters per database since stats_reset (NULL: never reset, start unknown).';

CREATE INDEX ix_database_stats_snapshot_target_captured
    ON postgresql.database_stats_snapshot
    (target_id, captured_at DESC);
