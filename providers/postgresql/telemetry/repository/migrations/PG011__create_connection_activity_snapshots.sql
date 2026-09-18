/*
===============================================================================
Migration No : 011
Version      : PG011
Title        : Create Connection Activity Snapshots

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Creates repository tables for PostgreSQL connection activity telemetry,
including system-level connection state, per-database cumulative session
statistics, and user/application connection breakdowns.
===============================================================================
*/

CREATE TABLE postgresql.connection_activity_snapshot
(
    snapshot_id BIGSERIAL PRIMARY KEY,
    target_id BIGINT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,

    total_client_connections BIGINT NOT NULL,
    active_connections BIGINT NOT NULL,
    idle_connections BIGINT NOT NULL,
    idle_in_transaction_connections BIGINT NOT NULL,
    idle_in_transaction_aborted_connections BIGINT NOT NULL,

    oldest_idle_state_change TIMESTAMPTZ NULL,
    oldest_idle_in_transaction_state_change TIMESTAMPTZ NULL,
    oldest_idle_in_transaction_aborted_state_change TIMESTAMPTZ NULL
);

CREATE INDEX ix_connection_activity_snapshot_target_captured
    ON postgresql.connection_activity_snapshot
    (
        target_id,
        captured_at DESC
    );


CREATE TABLE postgresql.connection_database_snapshot
(
    snapshot_id BIGSERIAL PRIMARY KEY,
    target_id BIGINT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,

    database_oid OID NOT NULL,
    database_name TEXT NOT NULL,

    sessions BIGINT NOT NULL,
    sessions_abandoned BIGINT NOT NULL,
    sessions_fatal BIGINT NOT NULL,
    sessions_killed BIGINT NOT NULL,

    session_time DOUBLE PRECISION NOT NULL,
    active_time DOUBLE PRECISION NOT NULL,
    idle_in_transaction_time DOUBLE PRECISION NOT NULL,

    stats_reset TIMESTAMPTZ NULL,

    current_connections BIGINT NOT NULL,
    active_connections BIGINT NOT NULL,
    idle_connections BIGINT NOT NULL,
    idle_in_transaction_connections BIGINT NOT NULL,
    idle_in_transaction_aborted_connections BIGINT NOT NULL
);

CREATE INDEX ix_connection_database_snapshot_target_captured
    ON postgresql.connection_database_snapshot
    (
        target_id,
        captured_at DESC
    );

CREATE INDEX ix_connection_database_snapshot_target_database_captured
    ON postgresql.connection_database_snapshot
    (
        target_id,
        database_oid,
        captured_at DESC
    );


CREATE TABLE postgresql.connection_breakdown_snapshot
(
    snapshot_id BIGSERIAL PRIMARY KEY,
    target_id BIGINT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,

    breakdown_type VARCHAR(32) NOT NULL,
    dimension_value TEXT NOT NULL,
    state TEXT NULL,
    connection_count BIGINT NOT NULL,

    CONSTRAINT ck_connection_breakdown_type
        CHECK (breakdown_type IN ('USER', 'APPLICATION'))
);

CREATE INDEX ix_connection_breakdown_snapshot_target_captured
    ON postgresql.connection_breakdown_snapshot
    (
        target_id,
        captured_at DESC
    );

CREATE INDEX ix_connection_breakdown_snapshot_dimension
    ON postgresql.connection_breakdown_snapshot
    (
        target_id,
        breakdown_type,
        dimension_value,
        captured_at DESC
    );