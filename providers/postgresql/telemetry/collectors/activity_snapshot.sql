/*
===============================================================================
Key        : PG_ACTIVITY_SNAPSHOT
Name       : Activity Snapshot
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Collects every session of pg_stat_activity: who, where, state, waits and
the current statement. A session waiting on a lock carries the sessions
blocking it and, from PostgreSQL 14, when the wait began (pg_locks.waitstart
through query_to_xml, so one script runs on every version). Keystone's own
sessions are left out: they must not look like the customer's workload.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp() AS captured_at,
        pg_backend_pid() AS collector_pid
),

lock_wait AS
(
    SELECT
        ((xpath('pid/text()', r))[1])::text::integer         AS pid,
        ((xpath('waitstart/text()', r))[1])::text::timestamptz AS lock_wait_start
    FROM unnest(xpath('/table/row', query_to_xml(
        CASE WHEN current_setting('server_version_num')::integer >= 140000
             THEN 'SELECT pid, min(waitstart) AS waitstart FROM pg_catalog.pg_locks '
                  'WHERE NOT granted AND pid IS NOT NULL GROUP BY pid'
             ELSE 'SELECT NULL::integer AS pid, NULL::timestamptz AS waitstart WHERE false'
        END, false, false, ''))) AS r
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

    CASE WHEN a.wait_event_type = 'Lock'
         THEN pg_catalog.pg_blocking_pids(a.pid) END AS blocked_by,
    w.lock_wait_start,

    c.captured_at

FROM pg_catalog.pg_stat_activity AS a
CROSS JOIN collection_context AS c
LEFT JOIN lock_wait AS w
    ON w.pid = a.pid

WHERE a.pid <> c.collector_pid
  AND a.application_name IS DISTINCT FROM 'keystone'     -- Keystone's other collectors

ORDER BY
    a.pid;