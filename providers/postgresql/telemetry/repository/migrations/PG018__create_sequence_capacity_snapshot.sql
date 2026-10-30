/*
===============================================================================
Migration No    : 018
Version         : PG018
Title           : Sequence Capacity Snapshot

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Creates the repository table for PG_SEQUENCE_CAPACITY: a DATABASE row per
collected database and a SEQUENCE row per sequence with its limits, the column
it feeds and, when readable, its last value.
===============================================================================
*/

CREATE TABLE postgresql.sequence_capacity_snapshot
(
    snapshot_id     BIGSERIAL PRIMARY KEY,
    target_id       BIGINT      NOT NULL,
    captured_at     TIMESTAMPTZ NOT NULL,
    record_type     TEXT        NOT NULL,         -- DATABASE | SEQUENCE
    database_name   TEXT        NOT NULL,

    schema_name     TEXT,
    sequence_name   TEXT,
    data_type       TEXT,
    min_value       NUMERIC,
    max_value       NUMERIC,
    increment_by    BIGINT,
    is_cycle        BOOLEAN,
    is_readable     BOOLEAN,
    last_value      NUMERIC,                      -- NULL: not readable, or never used
    table_name      TEXT,
    column_name     TEXT,
    column_type     TEXT,

    CONSTRAINT ck_sequence_capacity_snapshot_record_type CHECK (record_type IN ('DATABASE', 'SEQUENCE'))
);

COMMENT ON COLUMN postgresql.sequence_capacity_snapshot.is_readable IS
'Whether the collecting role has SELECT or USAGE on the sequence; without it last_value cannot be read (pg_monitor is not enough).';

CREATE INDEX ix_sequence_capacity_snapshot_target_captured
    ON postgresql.sequence_capacity_snapshot (target_id, captured_at DESC);
