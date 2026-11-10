/*
===============================================================================
Migration No    : 022
Version         : PG022
Title           : Index Definitions, Table Structure and Extensions

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Adds index definitions to index_usage_snapshot (method, key columns, operator
classes, expressions, predicate) and creates the repository tables of
PG_TABLE_STRUCTURE (foreign keys with index coverage, unlogged tables) and
PG_EXTENSIONS (installed and package versions per database).
===============================================================================
*/

ALTER TABLE postgresql.index_usage_snapshot
    ADD COLUMN IF NOT EXISTS access_method     TEXT,
    ADD COLUMN IF NOT EXISTS key_count         INTEGER,
    ADD COLUMN IF NOT EXISTS index_keys        TEXT,
    ADD COLUMN IF NOT EXISTS index_opclasses   TEXT,
    ADD COLUMN IF NOT EXISTS index_collations  TEXT,
    ADD COLUMN IF NOT EXISTS index_expressions TEXT,
    ADD COLUMN IF NOT EXISTS index_predicate   TEXT,
    ADD COLUMN IF NOT EXISTS index_definition  TEXT;

COMMENT ON COLUMN postgresql.index_usage_snapshot.index_keys IS
'pg_index.indkey: table column numbers, key columns first (key_count), then INCLUDE columns; 0 is an expression.';


CREATE TABLE postgresql.table_structure_snapshot
(
    snapshot_id       BIGSERIAL PRIMARY KEY,
    target_id         BIGINT      NOT NULL,
    captured_at       TIMESTAMPTZ NOT NULL,
    record_type       TEXT        NOT NULL,       -- DATABASE | FOREIGN_KEY | UNLOGGED_TABLE
    database_name     TEXT        NOT NULL,

    schema_name       TEXT,
    table_name        TEXT,
    constraint_name   TEXT,
    key_columns       TEXT,
    referenced_table  TEXT,
    has_index         BOOLEAN,
    table_size_bytes  BIGINT,
    extension_owned   BOOLEAN,

    CONSTRAINT ck_table_structure_snapshot_record_type
        CHECK (record_type IN ('DATABASE', 'FOREIGN_KEY', 'UNLOGGED_TABLE'))
);

COMMENT ON COLUMN postgresql.table_structure_snapshot.has_index IS
'A valid, non-partial index on the referencing table starts with exactly the foreign key columns, in any order.';

CREATE INDEX ix_table_structure_snapshot_target_captured
    ON postgresql.table_structure_snapshot (target_id, captured_at DESC);


CREATE TABLE postgresql.extension_snapshot
(
    snapshot_id        BIGSERIAL PRIMARY KEY,
    target_id          BIGINT      NOT NULL,
    captured_at        TIMESTAMPTZ NOT NULL,
    record_type        TEXT        NOT NULL,      -- DATABASE | EXTENSION
    database_name      TEXT        NOT NULL,

    extension_name     TEXT,
    installed_version  TEXT,
    default_version    TEXT,                      -- the package on the server; NULL if not available
    schema_name        TEXT,

    CONSTRAINT ck_extension_snapshot_record_type CHECK (record_type IN ('DATABASE', 'EXTENSION'))
);

CREATE INDEX ix_extension_snapshot_target_captured
    ON postgresql.extension_snapshot (target_id, captured_at DESC);
