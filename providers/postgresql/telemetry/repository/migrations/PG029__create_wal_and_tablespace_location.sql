/*
===============================================================================
Migration No    : 029
Version         : PG029
Title           : WAL and Tablespace Locations

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : NODE

Description
-----------
Creates the repository tables of two locations PostgreSQL writes to besides
the data directory:
- data_path_snapshot: from the host collector (PG_HOST_SNAPSHOT), each data
  directory a postmaster runs with and where its pg_wal really is, or why
  that could not be read (DIRECT, SUDO, DENIED, NOT_FOUND).
- tablespace_snapshot: from PG_TABLESPACES, every tablespace with its
  directory (empty for pg_default and pg_global) and size.
===============================================================================
*/

CREATE TABLE postgresql.data_path_snapshot
(
    snapshot_id     BIGSERIAL PRIMARY KEY,
    target_id       BIGINT      NOT NULL,
    captured_at     TIMESTAMPTZ NOT NULL,
    data_directory  TEXT,
    wal_location    TEXT,
    read_via        TEXT        NOT NULL,

    CONSTRAINT ck_data_path_snapshot_read_via
        CHECK (read_via IN ('DIRECT', 'SUDO', 'DENIED', 'NOT_FOUND'))
);

COMMENT ON TABLE postgresql.data_path_snapshot IS
'Where pg_wal of each running data directory points on the host; DENIED when the SSH user may not look inside the data directory, NOT_FOUND when no postmaster was seen.';

CREATE INDEX ix_data_path_snapshot_target_captured
    ON postgresql.data_path_snapshot
    (target_id, captured_at DESC);


CREATE TABLE postgresql.tablespace_snapshot
(
    snapshot_id      BIGSERIAL PRIMARY KEY,
    target_id        BIGINT      NOT NULL,
    captured_at      TIMESTAMPTZ NOT NULL,
    tablespace_name  TEXT        NOT NULL,
    location         TEXT,
    size_bytes       BIGINT
);

COMMENT ON TABLE postgresql.tablespace_snapshot IS
'Tablespaces per node: directory (pg_tablespace_location; empty inside the data directory) and size.';

CREATE INDEX ix_tablespace_snapshot_target_captured
    ON postgresql.tablespace_snapshot
    (target_id, captured_at DESC);
