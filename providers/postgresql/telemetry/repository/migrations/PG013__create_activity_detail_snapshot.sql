/*
===============================================================================
Migration No    : 013
Version         : PG013
Title           : Activity Detail Snapshot

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Creates the repository table for backend/session-level PostgreSQL activity
evidence collected from pg_stat_activity.

The evidence is reusable across health assessment, transaction analysis,
query analysis, wait analysis, and future performance engineering.
===============================================================================
*/


CREATE TABLE postgresql.activity_snapshot
(
    snapshot_id             BIGSERIAL       NOT NULL,
    target_id               BIGINT          NOT NULL,
    captured_at             TIMESTAMPTZ     NOT NULL,

    database_oid            OID,
    database_name           TEXT,

    pid                      INTEGER         NOT NULL,
    leader_pid               INTEGER,

    user_oid                 OID,
    user_name                TEXT,

    application_name         TEXT,

    client_addr              INET,
    client_hostname          TEXT,
    client_port              INTEGER,

    backend_start            TIMESTAMPTZ,
    transaction_start        TIMESTAMPTZ,
    query_start              TIMESTAMPTZ,
    state_change             TIMESTAMPTZ,

    wait_event_type          TEXT,
    wait_event               TEXT,
    state                    TEXT,

    backend_xid              XID,
    backend_xmin             XID,

    query_id                 BIGINT,
    query_text               TEXT,

    backend_type             TEXT,

    CONSTRAINT pk_postgresql_activity_snapshot
        PRIMARY KEY (snapshot_id),

    CONSTRAINT fk_postgresql_activity_snapshot_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target (target_id)
);


CREATE INDEX ix_postgresql_activity_snapshot_target_captured
    ON postgresql.activity_snapshot
    (
        target_id,
        captured_at DESC
    );


CREATE INDEX ix_postgresql_activity_snapshot_target_pid_captured
    ON postgresql.activity_snapshot
    (
        target_id,
        pid,
        captured_at DESC
    );