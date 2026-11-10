/*
===============================================================================
Key        : PG_VACUUM_ANALYZE
Name       : Vacuum & Analyze Statistics
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Collects raw table-level vacuum and analyze statistics including live/dead
tuple estimates, modification counters, last maintenance timestamps and
vacuum/analyze execution counters. A DATABASE row per collected database
marks it as read even when it has no tables, so an old snapshot is not taken
for the present.
===============================================================================
*/

WITH snapshot AS
(
    SELECT statement_timestamp() AS captured_at
)
SELECT
    'DATABASE'::text AS record_type,
    d.oid AS database_oid,
    current_database() AS database_name,
    NULL::name AS schema_name,
    NULL::oid AS object_oid,
    NULL::name AS object_name,
    NULL::boolean AS is_partition,
    NULL::bigint AS n_live_tup,
    NULL::bigint AS n_dead_tup,
    NULL::bigint AS n_mod_since_analyze,
    NULL::bigint AS n_ins_since_vacuum,
    NULL::timestamptz AS last_vacuum,
    NULL::timestamptz AS last_autovacuum,
    NULL::timestamptz AS last_analyze,
    NULL::timestamptz AS last_autoanalyze,
    NULL::bigint AS vacuum_count,
    NULL::bigint AS autovacuum_count,
    NULL::bigint AS analyze_count,
    NULL::bigint AS autoanalyze_count,
    snap.captured_at
FROM pg_database d
CROSS JOIN snapshot snap
WHERE d.datname = current_database()

UNION ALL

SELECT
    'TABLE'::text,
    d.oid AS database_oid,
    current_database() AS database_name,

    n.nspname AS schema_name,
    c.oid AS object_oid,
    c.relname AS object_name,

    c.relispartition AS is_partition,

    s.n_live_tup,
    s.n_dead_tup,
    s.n_mod_since_analyze,
    s.n_ins_since_vacuum,

    s.last_vacuum,
    s.last_autovacuum,
    s.last_analyze,
    s.last_autoanalyze,

    s.vacuum_count,
    s.autovacuum_count,
    s.analyze_count,
    s.autoanalyze_count,

    snap.captured_at

FROM pg_stat_user_tables s
JOIN pg_class c
    ON c.oid = s.relid
JOIN pg_namespace n
    ON n.oid = c.relnamespace
JOIN pg_database d
    ON d.datname = current_database()
CROSS JOIN snapshot snap

ORDER BY
    record_type,
    schema_name NULLS FIRST,
    object_name NULLS FIRST;