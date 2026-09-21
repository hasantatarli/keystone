/*
===============================================================================
Migration No    : 012
Version         : PG012
Title           : Host Telemetry Snapshots

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : NODE

Description
-----------
Creates repository tables for host-level evidence associated with PostgreSQL
NODE targets.

Host evidence may be collected automatically from the operating system or
provided manually when direct operating system access is unavailable.
===============================================================================
*/


CREATE TABLE postgresql.host_snapshot
(
    snapshot_id             BIGSERIAL       NOT NULL,
    target_id               BIGINT          NOT NULL,
    captured_at             TIMESTAMPTZ     NOT NULL,

    source_type             VARCHAR(20)     NOT NULL,

    hostname                VARCHAR(255),

    os_family               VARCHAR(30),
    os_name                 VARCHAR(100),
    os_version              VARCHAR(100),

    uptime_seconds          BIGINT,

    logical_cpu_count       INTEGER,

    memory_total_bytes      BIGINT,
    memory_available_bytes  BIGINT,
    memory_used_bytes       BIGINT,

    swap_total_bytes        BIGINT,
    swap_used_bytes         BIGINT,

    CONSTRAINT pk_postgresql_host_snapshot
        PRIMARY KEY (snapshot_id),

    CONSTRAINT fk_postgresql_host_snapshot_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target (target_id),

    CONSTRAINT ck_postgresql_host_snapshot_source
        CHECK (source_type IN ('AUTOMATED', 'MANUAL'))
);


CREATE INDEX ix_postgresql_host_snapshot_target_captured
    ON postgresql.host_snapshot
    (
        target_id,
        captured_at DESC
    );


CREATE TABLE postgresql.storage_snapshot
(
    snapshot_id             BIGSERIAL       NOT NULL,
    target_id               BIGINT          NOT NULL,
    captured_at             TIMESTAMPTZ     NOT NULL,

    source_type             VARCHAR(20)     NOT NULL,

    device                  VARCHAR(255),
    mount_point             VARCHAR(500)    NOT NULL,

    total_bytes             BIGINT,
    used_bytes              BIGINT,
    available_bytes         BIGINT,

    CONSTRAINT pk_postgresql_storage_snapshot
        PRIMARY KEY (snapshot_id),

    CONSTRAINT fk_postgresql_storage_snapshot_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target (target_id),

    CONSTRAINT ck_postgresql_storage_snapshot_source
        CHECK (source_type IN ('AUTOMATED', 'MANUAL'))
);


CREATE INDEX ix_postgresql_storage_snapshot_target_captured
    ON postgresql.storage_snapshot
    (
        target_id,
        captured_at DESC
    );