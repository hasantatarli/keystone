/*
===============================================================================
Title       : Keystone Repository Bootstrap

Author      : Hasan Tatarlı
Applies To  : PostgreSQL

Description
-----------
Creates the minimum repository infrastructure required by Keystone.
This script is intended for initial installation and must be idempotent.
===============================================================================
*/

CREATE SCHEMA IF NOT EXISTS keystone;


CREATE TABLE IF NOT EXISTS keystone.control
(
    control_id      BIGINT GENERATED ALWAYS AS IDENTITY,

    name            VARCHAR(150) NOT NULL,
    value           TEXT         NOT NULL,
    value_type      VARCHAR(30)  NOT NULL,
    namespace       VARCHAR(100) NOT NULL,
    description     VARCHAR(500),

    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
    updated_by      VARCHAR(128) NOT NULL,

    CONSTRAINT pk_control
        PRIMARY KEY (control_id),

    CONSTRAINT uq_control_name
        UNIQUE (name)
);


CREATE TABLE IF NOT EXISTS keystone.migration_history
(
    execution_id       BIGINT GENERATED ALWAYS AS IDENTITY,

    component          VARCHAR(150) NOT NULL,

    migration_no       INTEGER      NOT NULL,
    version            VARCHAR(50)  NOT NULL,
    file_name          VARCHAR(255) NOT NULL,
    description        VARCHAR(500) NOT NULL,

    checksum           CHAR(64)     NOT NULL,

    status             VARCHAR(20)  NOT NULL,

    executed_at        TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
    executed_by        VARCHAR(128) NOT NULL,

    execution_time_ms  BIGINT,

    status_message     TEXT,
    error_message      TEXT,

    CONSTRAINT pk_migration_history
        PRIMARY KEY (execution_id),

    CONSTRAINT ck_migration_history_status
        CHECK (status IN ('SUCCESS', 'FAILED', 'SKIPPED')),

    CONSTRAINT ck_migration_history_execution_time
        CHECK (
            execution_time_ms IS NULL
            OR execution_time_ms >= 0
        ),

    CONSTRAINT ck_migration_history_checksum
        CHECK (
            checksum ~ '^[0-9A-Fa-f]{64}$'
        )
);


COMMENT ON SCHEMA keystone IS
'Keystone internal repository.';

COMMENT ON TABLE keystone.control IS
'Stores the current configuration and state of Keystone components.';

COMMENT ON TABLE keystone.migration_history IS
'Stores the execution history of Keystone repository and provider migrations.';


INSERT INTO keystone.control
(
    name,
    value,
    value_type,
    namespace,
    description,
    updated_by
)
VALUES
(
    'Repository.Version',
    '0.1.0',
    'VERSION',
    'Repository',
    'Current Keystone repository version.',
    'bootstrap'
)
ON CONFLICT (name) DO NOTHING;