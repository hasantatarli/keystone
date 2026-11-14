/*
===============================================================================
Migration No    : 027
Version         : PG027
Title           : Table and Index Bloat Snapshot

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Creates the repository table of PG_TABLE_BLOAT: a DATABASE row per database
(whether pgstattuple was usable) and an OBJECT row per table or btree index
of at least 100 MB with its size, estimated wasted bytes and the method
(PGSTATTUPLE, STATISTICS, or NULL when neither could measure it).
===============================================================================
*/

CREATE TABLE postgresql.table_bloat_snapshot
(
    snapshot_id            BIGSERIAL PRIMARY KEY,
    target_id              BIGINT      NOT NULL,
    captured_at            TIMESTAMPTZ NOT NULL,
    record_type            TEXT        NOT NULL,       -- DATABASE | OBJECT
    database_name          TEXT        NOT NULL,
    object_kind            TEXT,                       -- TABLE | INDEX
    schema_name            TEXT,
    object_name            TEXT,
    table_name             TEXT,
    size_bytes             BIGINT,
    wasted_bytes           BIGINT,
    pgstattuple_available  BOOLEAN,
    method                 TEXT,

    CONSTRAINT ck_table_bloat_snapshot_record_type
        CHECK (record_type IN ('DATABASE', 'OBJECT'))
);

COMMENT ON TABLE postgresql.table_bloat_snapshot IS
'Estimated wasted space of tables and btree indexes >= 100 MB; method NULL: not measurable with the role''s privileges.';

CREATE INDEX ix_table_bloat_snapshot_target_captured
    ON postgresql.table_bloat_snapshot
    (target_id, database_name, captured_at DESC);
