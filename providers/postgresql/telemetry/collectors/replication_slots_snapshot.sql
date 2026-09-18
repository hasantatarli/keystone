/*
===============================================================================
Key        : PG_REPLICATION_SLOTS
Name       : Replication Slots
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Collects raw PostgreSQL replication slot state and WAL position information
for physical and logical replication slots.
===============================================================================
*/

WITH collection_context AS
(
    SELECT clock_timestamp() AS captured_at
)
SELECT
    s.slot_name,
    s.plugin,
    s.slot_type,
    s.database,
    s.temporary,
    s.active,
    s.active_pid,
    s.xmin AS slot_xmin,
    s.catalog_xmin AS catalog_xmin,
    s.restart_lsn,
    s.confirmed_flush_lsn,
    s.wal_status,
    s.safe_wal_size,
    s.two_phase,
    s.conflicting,
    s.invalidation_reason,
    s.failover,
    c.captured_at
FROM pg_catalog.pg_replication_slots AS s
CROSS JOIN collection_context AS c
ORDER BY
    s.slot_name;