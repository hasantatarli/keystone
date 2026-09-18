/*
===============================================================================
Key        : PG_REPLICATION_STATUS
Name       : Replication Status
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Collects raw PostgreSQL replication status and WAL position information
from the primary system for replication monitoring.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp()    AS captured_at,
        pg_current_wal_lsn() AS current_wal_lsn
),
replication_info AS
(
    SELECT
        r.application_name,
        r.client_addr,
        r.client_port,
        r.backend_start,
        r.state,
        r.sync_state,
        r.sent_lsn,
        r.write_lsn,
        r.flush_lsn,
        r.replay_lsn,
        r.write_lag,
        r.flush_lag,
        r.replay_lag,
        r.reply_time,
        r.backend_xmin
    FROM pg_catalog.pg_stat_replication AS r
)
SELECT
    'SYSTEM'::text                   AS record_type,
    NULL::text                       AS application_name,
    NULL::inet                       AS client_addr,
    NULL::integer                    AS client_port,
    NULL::timestamptz                AS backend_start,
    NULL::text                       AS state,
    NULL::text                       AS sync_state,
    NULL::pg_lsn                     AS sent_lsn,
    NULL::pg_lsn                     AS write_lsn,
    NULL::pg_lsn                     AS flush_lsn,
    NULL::pg_lsn                     AS replay_lsn,
    NULL::interval                   AS write_lag,
    NULL::interval                   AS flush_lag,
    NULL::interval                   AS replay_lag,
    NULL::timestamptz                AS reply_time,
    NULL::xid                        AS backend_xmin,
    c.current_wal_lsn,
    COUNT(r.application_name)::bigint AS connected_replica_count,
    c.captured_at
FROM collection_context AS c
LEFT JOIN replication_info AS r
    ON TRUE
GROUP BY
    c.current_wal_lsn,
    c.captured_at

UNION ALL

SELECT
    'REPLICA'::text                  AS record_type,
    r.application_name,
    r.client_addr,
    r.client_port,
    r.backend_start,
    r.state,
    r.sync_state,
    r.sent_lsn,
    r.write_lsn,
    r.flush_lsn,
    r.replay_lsn,
    r.write_lag,
    r.flush_lag,
    r.replay_lag,
    r.reply_time,
    r.backend_xmin,
    c.current_wal_lsn,
    NULL::bigint                     AS connected_replica_count,
    c.captured_at
FROM replication_info AS r
CROSS JOIN collection_context AS c

ORDER BY
    record_type,
    application_name NULLS FIRST,
    client_addr NULLS FIRST;