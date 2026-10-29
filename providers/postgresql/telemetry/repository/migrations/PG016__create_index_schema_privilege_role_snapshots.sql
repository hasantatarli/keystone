/*
===============================================================================
Migration No    : 016
Version         : PG016
Title           : Index Usage, Schema Privilege and Role Snapshots

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : NODE_DATABASE / DATABASE / SYSTEM

Description
-----------
Creates repository tables for PG_INDEX_USAGE (every node, every database),
PG_SCHEMA_PRIVILEGES (every database) and PG_ROLES (system). The DATABASE rows
of the first two record that a database was collected, even without objects.
===============================================================================
*/

CREATE TABLE postgresql.index_usage_snapshot
(
    snapshot_id        BIGSERIAL PRIMARY KEY,
    target_id          BIGINT      NOT NULL,
    captured_at        TIMESTAMPTZ NOT NULL,
    record_type        TEXT        NOT NULL,      -- DATABASE | INDEX
    database_name      TEXT        NOT NULL,

    in_recovery        BOOLEAN,                   -- DATABASE rows
    stats_since        TIMESTAMPTZ,               -- DATABASE rows
    stats_since_start  BOOLEAN,                   -- DATABASE rows: never reset, server start used

    schema_name        TEXT,
    table_name         TEXT,
    index_name         TEXT,
    idx_scan           BIGINT,
    index_size_bytes   BIGINT,
    is_valid           BOOLEAN,
    is_unique          BOOLEAN,
    constraint_type    TEXT,                      -- p / u / x when the index backs a constraint
    being_built        BOOLEAN,

    CONSTRAINT ck_index_usage_snapshot_record_type CHECK (record_type IN ('DATABASE', 'INDEX'))
);

COMMENT ON COLUMN postgresql.index_usage_snapshot.stats_since IS
'pg_stat_database.stats_reset of the database on this node; the server start time when statistics were never reset (stats_since_start).';

CREATE INDEX ix_index_usage_snapshot_target_captured
    ON postgresql.index_usage_snapshot (target_id, captured_at DESC);


CREATE TABLE postgresql.schema_privilege_snapshot
(
    snapshot_id     BIGSERIAL PRIMARY KEY,
    target_id       BIGINT      NOT NULL,
    captured_at     TIMESTAMPTZ NOT NULL,
    record_type     TEXT        NOT NULL,         -- DATABASE | SCHEMA
    database_name   TEXT        NOT NULL,

    schema_name     TEXT,
    schema_owner    TEXT,
    public_usage    BOOLEAN,
    public_create   BOOLEAN,

    CONSTRAINT ck_schema_privilege_snapshot_record_type CHECK (record_type IN ('DATABASE', 'SCHEMA'))
);

CREATE INDEX ix_schema_privilege_snapshot_target_captured
    ON postgresql.schema_privilege_snapshot (target_id, captured_at DESC);


CREATE TABLE postgresql.role_snapshot
(
    snapshot_id      BIGSERIAL PRIMARY KEY,
    target_id        BIGINT      NOT NULL,
    captured_at      TIMESTAMPTZ NOT NULL,

    role_oid         OID         NOT NULL,
    role_name        TEXT        NOT NULL,
    can_login        BOOLEAN     NOT NULL,
    is_superuser     BOOLEAN     NOT NULL,
    can_create_role  BOOLEAN     NOT NULL,
    can_create_db    BOOLEAN     NOT NULL,
    is_replication   BOOLEAN     NOT NULL,
    bypass_rls       BOOLEAN     NOT NULL,
    valid_until      TIMESTAMPTZ
);

CREATE INDEX ix_role_snapshot_target_captured
    ON postgresql.role_snapshot (target_id, captured_at DESC);
