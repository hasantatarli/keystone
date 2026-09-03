/*
===============================================================================
Migration No : 003
Version      : V003
Title        : Collector Assignment

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Separates collector definitions from target-specific execution assignments.
Renames the collector table, removes scheduling information from the definition,
and creates collector assignments for target-specific execution behavior.
===============================================================================
*/

ALTER TABLE keystone.collector
RENAME TO collector_definition;


ALTER TABLE keystone.collector_definition
RENAME CONSTRAINT pk_collector
TO pk_collector_definition;


ALTER TABLE keystone.collector_definition
RENAME CONSTRAINT uq_collector_component_name
TO uq_collector_definition_component_name;


ALTER TABLE keystone.collector_definition
DROP CONSTRAINT ck_collector_interval;


ALTER TABLE keystone.collector_definition
DROP COLUMN interval_seconds;


CREATE TABLE keystone.collector_assignment
(
    assignment_id       BIGINT GENERATED ALWAYS AS IDENTITY,

    collector_id        BIGINT      NOT NULL,
    target_id           BIGINT      NOT NULL,

    execution_mode      VARCHAR(20) NOT NULL,
    interval_seconds    INTEGER,

    is_enabled          BOOLEAN     NOT NULL DEFAULT TRUE,
    description         VARCHAR(500),

    CONSTRAINT pk_collector_assignment
        PRIMARY KEY (assignment_id),

    CONSTRAINT fk_collector_assignment_collector
        FOREIGN KEY (collector_id)
        REFERENCES keystone.collector_definition (collector_id),

    CONSTRAINT fk_collector_assignment_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target (target_id),

    CONSTRAINT uq_collector_assignment
        UNIQUE (collector_id, target_id),

    CONSTRAINT ck_collector_assignment_execution_mode
        CHECK (
            execution_mode IN ('ON_DEMAND', 'SCHEDULED')
        ),

    CONSTRAINT ck_collector_assignment_interval
        CHECK (
            (execution_mode = 'ON_DEMAND' AND interval_seconds IS NULL)
            OR
            (execution_mode = 'SCHEDULED' AND interval_seconds > 0)
        )
);