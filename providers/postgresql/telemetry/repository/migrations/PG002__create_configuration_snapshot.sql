/*
===============================================================================
Migration No : 002
Version      : PG002
Title        : Create PostgreSQL Configuration Snapshot

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : NODE

Description
-----------
Creates the PostgreSQL configuration snapshot table.

The table stores historical PostgreSQL configuration values collected from
pg_settings. Each collection produces a point-in-time snapshot of configuration
values for a target node.

Configuration metadata such as category, unit, data type, context, source, and
pending restart state is retained to support historical comparison, change
detection, findings, and future recommendation logic.
===============================================================================
*/

CREATE TABLE postgresql.configuration_snapshot
(
    target_id           BIGINT        NOT NULL,
    captured_at         TIMESTAMPTZ   NOT NULL,

    setting_name        VARCHAR(128)  NOT NULL,
    setting_value       TEXT          NULL,

    unit                VARCHAR(32)   NULL,
    setting_type        VARCHAR(32)   NULL,
    category            VARCHAR(128)  NULL,
    context             VARCHAR(32)   NULL,
    source              VARCHAR(64)   NULL,
    pending_restart     BOOLEAN       NULL,

    CONSTRAINT pk_configuration_snapshot
        PRIMARY KEY
        (
            target_id,
            captured_at,
            setting_name
        ),

    CONSTRAINT fk_configuration_snapshot_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target(target_id)
);


CREATE INDEX ix_configuration_snapshot_setting_history
    ON postgresql.configuration_snapshot
    (
        target_id,
        setting_name,
        captured_at DESC
    );