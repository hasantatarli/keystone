/*
===============================================================================
Key        : PG_ACTIVITY_SNAPSHOT
Name       : Activity Snapshot
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Collects backend/session-level PostgreSQL activity evidence from
pg_stat_activity for health assessment, transaction analysis, query analysis,
wait analysis, and future performance engineering.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp() AS captured_at,
        pg_backend_pid() AS collector_pid
)
SELECT
    a.datid AS database_oid,
    a.datname AS database_name,

    a.pid,
    a.leader_pid,

    a.usesysid AS user_oid,
    a.usename AS user_name,

    a.application_name,

    a.client_addr,
    a.client_hostname,
    a.client_port,

    a.backend_start,
    a.xact_start AS transaction_start,
    a.query_start,
    a.state_change,

    a.wait_event_type,
    a.wait_event,
    a.state,

    a.backend_xid,
    a.backend_xmin,

    a.query_id,
    a.query AS query_text,

    a.backend_type,

    c.captured_at

FROM pg_catalog.pg_stat_activity AS a
CROSS JOIN collection_context AS c

WHERE a.pid <> c.collector_pid

ORDER BY
    a.pid;