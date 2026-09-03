/*
===============================================================================
Migration No : 005
Version      : PG005
Title        : Extend Table Capacity Object Identity

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : DATABASE


Description
-----------
Extends the PostgreSQL table capacity snapshot to support materialized views
by using generic object identity columns and adding an object type.
===============================================================================
*/

ALTER TABLE postgresql.table_capacity_snapshot
    RENAME COLUMN table_oid TO object_oid;

ALTER TABLE postgresql.table_capacity_snapshot
    RENAME COLUMN table_name TO object_name;

ALTER TABLE postgresql.table_capacity_snapshot
    ADD COLUMN object_type VARCHAR(32) NOT NULL;