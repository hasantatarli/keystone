/*
===============================================================================
Migration No    : 026
Version         : PG026
Title           : Client Authentication Rules Snapshot

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : NODE

Description
-----------
Creates the repository table of PG_HBA_RULES: an ACCESS row saying whether
pg_hba_file_rules was readable, and a RULE row per pg_hba.conf line with its
connection type, databases, users, address and authentication method.
===============================================================================
*/

CREATE TABLE postgresql.hba_rule_snapshot
(
    snapshot_id   BIGSERIAL PRIMARY KEY,
    target_id     BIGINT      NOT NULL,
    captured_at   TIMESTAMPTZ NOT NULL,
    record_type   TEXT        NOT NULL,       -- ACCESS | RULE
    readable      BOOLEAN,
    line_number   INTEGER,
    conn_type     TEXT,
    databases     TEXT,
    users         TEXT,
    address       TEXT,
    netmask       TEXT,
    auth_method   TEXT,
    error         TEXT,

    CONSTRAINT ck_hba_rule_snapshot_record_type
        CHECK (record_type IN ('ACCESS', 'RULE'))
);

COMMENT ON TABLE postgresql.hba_rule_snapshot IS
'pg_hba_file_rules per node; readable = FALSE when the role lacks the privilege (superuser only by default).';

CREATE INDEX ix_hba_rule_snapshot_target_captured
    ON postgresql.hba_rule_snapshot
    (target_id, captured_at DESC);
