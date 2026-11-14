/*
===============================================================================
Key        : PG_DATABASE_STATS
Name       : Database Statistics
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Collects the cumulative counters of every connectable database from
pg_stat_database: committed and rolled back transactions, blocks read from
disk and found in shared buffers, temporary files and bytes, and when the
counters were last reset. Raw counters only: rates and ratios are derived by
Keystone from two snapshots or from the reset time (PG-PERF-002, PG-CAP-005).
===============================================================================
*/

WITH collection_context AS
(
    SELECT clock_timestamp() AS captured_at     -- one capture time for every row
)
SELECT
    d.datname::text          AS database_name,
    d.xact_commit,
    d.xact_rollback,
    d.blks_read,
    d.blks_hit,
    d.temp_files,
    d.temp_bytes,
    d.stats_reset,
    pg_catalog.pg_is_in_recovery() AS in_recovery,
    c.captured_at
FROM pg_catalog.pg_stat_database AS d
CROSS JOIN collection_context AS c
JOIN pg_catalog.pg_database AS db
    ON db.oid = d.datid
WHERE db.datallowconn
  AND NOT db.datistemplate
ORDER BY d.datname;
