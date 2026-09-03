/*
===============================================================================
Migration No : 001
Version      : V001
Title        : Inventory Foundation

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Creates the initial target inventory structure for Keystone.
===============================================================================
*/

CREATE TABLE keystone.target
(
    target_id         BIGINT GENERATED ALWAYS AS IDENTITY,

    parent_target_id  BIGINT,

    name              VARCHAR(150) NOT NULL,
    provider          VARCHAR(50)  NOT NULL,
    target_type       VARCHAR(30)  NOT NULL,
    environment       VARCHAR(50)  NOT NULL,

    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
    description       VARCHAR(500),

    CONSTRAINT pk_target
        PRIMARY KEY (target_id),

    CONSTRAINT fk_target_parent
        FOREIGN KEY (parent_target_id)
        REFERENCES keystone.target (target_id),

    CONSTRAINT ck_target_type
        CHECK (target_type IN ('SYSTEM', 'NODE', 'ENDPOINT')),

    CONSTRAINT ck_target_parent
        CHECK (target_id <> parent_target_id)
);

CREATE TABLE keystone.target_connection
(
    connection_id       BIGINT GENERATED ALWAYS AS IDENTITY,

    target_id           BIGINT       NOT NULL,

    connection_name     VARCHAR(150) NOT NULL,
    host                VARCHAR(255) NOT NULL,
    port                INTEGER,

    database_name       VARCHAR(150),
    username            VARCHAR(150),

    auth_type           VARCHAR(30)  NOT NULL,
    secret_reference    VARCHAR(500),

    connection_purpose  VARCHAR(30)  NOT NULL,

    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    description         VARCHAR(500),

    CONSTRAINT pk_target_connection
        PRIMARY KEY (connection_id),

    CONSTRAINT fk_target_connection_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target (target_id),

    CONSTRAINT ck_target_connection_port
        CHECK (port IS NULL OR port BETWEEN 1 AND 65535)
);  
  
  