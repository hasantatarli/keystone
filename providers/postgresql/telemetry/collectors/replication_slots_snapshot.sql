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
for physical and logical replication slots. The SYSTEM row is always returned,
so "no slots" is evidence. Columns newer than PostgreSQL 15 (conflicting 16+,
invalidation_reason and failover 17+) are read through to_jsonb, so one script
runs on every supported version and gives NULL where a column does not exist.
===============================================================================
*/

WITH collection_context AS
(
    SELECT clock_timestamp() AS captured_at
),
slots AS
(
    SELECT s.*, to_jsonb(s) AS j
    FROM pg_catalog.pg_replication_slots AS s
)
SELECT
    'SYSTEM'::text         AS record_type,
    (SELECT count(*) FROM pg_catalog.pg_replication_slots)::bigint AS slot_count,
    NULL::name             AS slot_name,
    NULL::name             AS plugin,
    NULL::text             AS slot_type,
    NULL::name             AS database,
    NULL::boolean          AS temporary,
    NULL::boolean          AS active,
    NULL::integer          AS active_pid,
    NULL::xid              AS slot_xmin,
    NULL::xid              AS catalog_xmin,
    NULL::pg_lsn           AS restart_lsn,
    NULL::pg_lsn           AS confirmed_flush_lsn,
    NULL::text             AS wal_status,
    NULL::bigint           AS safe_wal_size,
    NULL::boolean          AS two_phase,
    NULL::boolean          AS conflicting,
    NULL::text             AS invalidation_reason,
    NULL::boolean          AS failover,
    c.captured_at
FROM collection_context AS c

UNION ALL

SELECT
    'SLOT'::text,
    NULL::bigint,
    s.slot_name,
    s.plugin,
    s.slot_type,
    s.database,
    s.temporary,
    s.active,
    s.active_pid,
    s.xmin,
    s.catalog_xmin,
    s.restart_lsn,
    s.confirmed_flush_lsn,
    s.wal_status,
    s.safe_wal_size,
    s.two_phase,
    (s.j ->> 'conflicting')::boolean,
    s.j ->> 'invalidation_reason',
    COALESCE((s.j ->> 'failover')::boolean, false),
    c.captured_at
FROM slots AS s
CROSS JOIN collection_context AS c

ORDER BY
    record_type,
    slot_name NULLS FIRST;
