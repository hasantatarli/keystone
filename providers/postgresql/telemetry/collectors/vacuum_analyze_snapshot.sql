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
vacuum/analyze execution counters.
===============================================================================
*/

WITH snapshot AS
(
    SELECT statement_timestamp() AS captured_at
)
SELECT
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
    n.nspname,
    c.relname;