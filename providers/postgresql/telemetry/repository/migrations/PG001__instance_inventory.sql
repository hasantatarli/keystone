/*
===============================================================================
Migration No : 001
Version      : PG001
Title        : PostgreSQL Instance Inventory

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : NODE

Description
-----------
Creates the PostgreSQL provider schema and current-state instance inventory
table used by the Instance Snapshot collector.
===============================================================================
*/

CREATE SCHEMA IF NOT EXISTS postgresql;


CREATE TABLE postgresql.instance_inventory
(
    target_id               BIGINT      NOT NULL,

    server_version          VARCHAR(100),
    server_version_num      INTEGER,

    server_address          VARCHAR(255),
    server_port             INTEGER,

    current_database        VARCHAR(150),
    collector_user          VARCHAR(150),

    in_recovery             BOOLEAN,

    postmaster_start_time   TIMESTAMPTZ,
    system_identifier       VARCHAR(100),

    last_collected_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT pk_postgresql_instance_inventory
        PRIMARY KEY (target_id),

    CONSTRAINT fk_postgresql_instance_inventory_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target (target_id),

    CONSTRAINT ck_postgresql_instance_inventory_port
        CHECK (
            server_port IS NULL
            OR server_port BETWEEN 1 AND 65535
        )
);


COMMENT ON SCHEMA postgresql IS
'PostgreSQL provider repository objects.';

COMMENT ON TABLE postgresql.instance_inventory IS
'Stores the current PostgreSQL instance inventory state for each Keystone target.';

COMMENT ON COLUMN postgresql.instance_inventory.target_id IS
'Keystone target represented by this PostgreSQL instance inventory record.';

COMMENT ON COLUMN postgresql.instance_inventory.system_identifier IS
'PostgreSQL system identifier returned by pg_control_system().';

COMMENT ON COLUMN postgresql.instance_inventory.last_collected_at IS
'Time at which the instance inventory was last refreshed.';