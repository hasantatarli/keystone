/*
===============================================================================
Migration No    : 028
Version         : PG028
Title           : Query Statistics Snapshot

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Creates the repository table of PG_QUERY_STATS: a SYSTEM row (whether
pg_stat_statements is loaded, created in the database read and readable;
since when it counts; total time of all statements) and a QUERY row per
statement among the most expensive by time, temporary files or disk reads.
===============================================================================
*/

CREATE TABLE postgresql.query_stats_snapshot
(
    snapshot_id        BIGSERIAL PRIMARY KEY,
    target_id          BIGINT      NOT NULL,
    captured_at        TIMESTAMPTZ NOT NULL,
    record_type        TEXT        NOT NULL,       -- SYSTEM | QUERY
    preloaded          BOOLEAN,
    extension_created  BOOLEAN,
    available          BOOLEAN,
    stats_reset        TIMESTAMPTZ,
    all_total_ms       NUMERIC,
    queryid            BIGINT,
    database_name      TEXT,
    user_name          TEXT,
    calls              BIGINT,
    total_ms           NUMERIC,
    rows               BIGINT,
    shared_blks_hit    BIGINT,
    shared_blks_read   BIGINT,
    temp_blks_written  BIGINT,
    query_text         TEXT,

    CONSTRAINT ck_query_stats_snapshot_record_type
        CHECK (record_type IN ('SYSTEM', 'QUERY'))
);

COMMENT ON TABLE postgresql.query_stats_snapshot IS
'pg_stat_statements: most expensive statements since its reset (query text normalized by the extension).';

CREATE INDEX ix_query_stats_snapshot_target_captured
    ON postgresql.query_stats_snapshot
    (target_id, captured_at DESC);
