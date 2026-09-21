/*
===============================================================================
Migration No : 015
Version      : V015
Title        : Add Collector Execution Type

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds execution_type to collector definitions.

execution_scope defines where a collector executes:
SYSTEM, NODE, or DATABASE.

execution_type defines how a collector executes.
Initial supported execution types are SQL and SSH.
===============================================================================
*/

ALTER TABLE keystone.collector_definition
    ADD COLUMN execution_type VARCHAR(32) NOT NULL DEFAULT 'SQL';

ALTER TABLE keystone.collector_definition
    ADD CONSTRAINT ck_collector_definition_execution_type
    CHECK (execution_type IN ('SQL', 'SSH'));