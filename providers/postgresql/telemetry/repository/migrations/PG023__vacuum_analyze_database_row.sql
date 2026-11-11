/*
===============================================================================
Migration No    : 023
Version         : PG023
Title           : Vacuum Analyze Database Row

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Lets PG_VACUUM_ANALYZE store a DATABASE row per collected database besides
its TABLE rows, so a database without tables ends with its latest collection
instead of an older snapshot (lab hc110, 2026-11-10: dropped test tables were
still judged). Existing rows are TABLE rows.
===============================================================================
*/

ALTER TABLE postgresql.vacuum_analyze_snapshot
    ADD COLUMN IF NOT EXISTS record_type TEXT NOT NULL DEFAULT 'TABLE';

ALTER TABLE postgresql.vacuum_analyze_snapshot
    ALTER COLUMN schema_name  DROP NOT NULL,
    ALTER COLUMN object_oid   DROP NOT NULL,
    ALTER COLUMN object_name  DROP NOT NULL,
    ALTER COLUMN is_partition DROP NOT NULL;

ALTER TABLE postgresql.vacuum_analyze_snapshot
    ADD CONSTRAINT ck_vacuum_analyze_snapshot_record_type CHECK (record_type IN ('DATABASE', 'TABLE'));
