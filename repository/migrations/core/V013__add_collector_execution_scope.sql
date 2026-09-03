/*
===============================================================================
Migration No : 013
Version      : V013
Title        : Add Collector Execution Scope

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds execution_scope to collector definitions so collector execution behavior
can be driven by metadata rather than collector-specific worker logic.
===============================================================================
*/

ALTER TABLE keystone.collector_definition
    ADD COLUMN execution_scope VARCHAR(32) NOT NULL DEFAULT 'SYSTEM';

ALTER TABLE keystone.collector_definition
    ADD CONSTRAINT ck_collector_definition_execution_scope
    CHECK (execution_scope IN ('SYSTEM', 'NODE', 'DATABASE'));