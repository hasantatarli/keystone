/*
===============================================================================
Migration No : 002
Version      : V002
Title        : Collector Foundation

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Creates the initial collector definition structure for Keystone.
===============================================================================
*/

CREATE TABLE keystone.collector
(
    collector_id       BIGINT GENERATED ALWAYS AS IDENTITY,

    component          VARCHAR(150) NOT NULL,
    name               VARCHAR(150) NOT NULL,

    script_file        VARCHAR(255) NOT NULL,
    checksum           CHAR(64)     NOT NULL,

    interval_seconds   INTEGER      NOT NULL,

    is_active          BOOLEAN      NOT NULL DEFAULT TRUE,
    description        VARCHAR(500),

    CONSTRAINT pk_collector
        PRIMARY KEY (collector_id),

    CONSTRAINT uq_collector_component_name
        UNIQUE (component, name),

    CONSTRAINT ck_collector_interval
        CHECK (interval_seconds > 0)

);