/*
===============================================================================
Key        : PG_TABLE_ACCESS
Name       : Table Access
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Collects how every table of the database is read: sequential scans, rows they
read and index scans (cumulative counters of pg_stat_user_tables), the live
rows and the size of the table, and when the database's statistics were last
reset. A DATABASE row per collected database marks it as read. Raw counters
only: Keystone derives the period from two snapshots (PG-IDX-005).
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp() AS captured_at,
        (SELECT d.stats_reset FROM pg_catalog.pg_stat_database AS d
         WHERE d.datname = current_database()) AS stats_reset
)

SELECT
    'DATABASE'::text   AS record_type,
    current_database() AS database_name,
    NULL::text         AS schema_name,
    NULL::oid          AS object_oid,
    NULL::text         AS object_name,
    NULL::bigint       AS seq_scan,
    NULL::bigint       AS seq_tup_read,
    NULL::bigint       AS idx_scan,
    NULL::bigint       AS n_live_tup,
    NULL::bigint       AS table_size_bytes,
    c.stats_reset,
    c.captured_at
FROM collection_context AS c

UNION ALL

SELECT
    'TABLE'::text,
    current_database(),
    s.schemaname::text,
    s.relid,
    s.relname::text,
    s.seq_scan,
    s.seq_tup_read,
    s.idx_scan,
    s.n_live_tup,
    pg_catalog.pg_relation_size(s.relid),
    c.stats_reset,
    c.captured_at
FROM pg_catalog.pg_stat_user_tables AS s
CROSS JOIN collection_context AS c

ORDER BY record_type, schema_name NULLS FIRST, object_name NULLS FIRST;
