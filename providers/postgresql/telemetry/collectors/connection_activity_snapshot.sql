/*
===============================================================================
Key        : PG_CONNECTION_ACTIVITY
Name       : Connection Activity
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Collects cumulative PostgreSQL session statistics and current connection
activity for capacity, pooling, and connection behavior analysis.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp() AS captured_at,
        pg_backend_pid() AS collector_pid
),

client_activity AS
(
    SELECT
        a.*
    FROM pg_catalog.pg_stat_activity AS a
    CROSS JOIN collection_context AS c
    WHERE a.backend_type = 'client backend'
      AND a.pid <> c.collector_pid
),

system_activity AS
(
    SELECT
        COUNT(*) AS total_client_connections,

        COUNT(*) FILTER
        (
            WHERE state = 'active'
        ) AS active_connections,

        COUNT(*) FILTER
        (
            WHERE state = 'idle'
        ) AS idle_connections,

        COUNT(*) FILTER
        (
            WHERE state = 'idle in transaction'
        ) AS idle_in_transaction_connections,

        COUNT(*) FILTER
        (
            WHERE state = 'idle in transaction (aborted)'
        ) AS idle_in_transaction_aborted_connections,

        MIN(state_change) FILTER
        (
            WHERE state = 'idle'
        ) AS oldest_idle_state_change,

        MIN(state_change) FILTER
        (
            WHERE state = 'idle in transaction'
        ) AS oldest_idle_in_transaction_state_change,

        MIN(state_change) FILTER
        (
            WHERE state = 'idle in transaction (aborted)'
        ) AS oldest_idle_in_transaction_aborted_state_change
    FROM client_activity
),

database_activity AS
(
    SELECT
        datid AS database_oid,

        COUNT(*) AS current_connections,

        COUNT(*) FILTER
        (
            WHERE state = 'active'
        ) AS active_connections,

        COUNT(*) FILTER
        (
            WHERE state = 'idle'
        ) AS idle_connections,

        COUNT(*) FILTER
        (
            WHERE state = 'idle in transaction'
        ) AS idle_in_transaction_connections,

        COUNT(*) FILTER
        (
            WHERE state = 'idle in transaction (aborted)'
        ) AS idle_in_transaction_aborted_connections

    FROM client_activity
    WHERE datid IS NOT NULL
    GROUP BY datid
),

database_stats AS
(
    SELECT
        d.datid AS database_oid,
        d.datname AS database_name,

        d.sessions,
        d.sessions_abandoned,
        d.sessions_fatal,
        d.sessions_killed,

        d.session_time,
        d.active_time,
        d.idle_in_transaction_time,

        d.stats_reset,

        COALESCE(a.current_connections, 0) AS current_connections,
        COALESCE(a.active_connections, 0) AS active_connections,
        COALESCE(a.idle_connections, 0) AS idle_connections,
        COALESCE(a.idle_in_transaction_connections, 0)
            AS idle_in_transaction_connections,
        COALESCE(a.idle_in_transaction_aborted_connections, 0)
            AS idle_in_transaction_aborted_connections

    FROM pg_catalog.pg_stat_database AS d
    JOIN pg_catalog.pg_database AS db
        ON db.oid = d.datid
    LEFT JOIN database_activity AS a
        ON a.database_oid = d.datid
    WHERE db.datallowconn = true
    AND db.datistemplate = false
),

user_breakdown AS
(
    SELECT
        'USER'::text AS breakdown_type,
        usename AS dimension_value,
        state,
        COUNT(*) AS connection_count
    FROM client_activity
    WHERE usename IS NOT NULL
    GROUP BY
        usename,
        state
),

application_breakdown AS
(
    SELECT
        'APPLICATION'::text AS breakdown_type,
        COALESCE(NULLIF(application_name, ''), '(unknown)')
            AS dimension_value,
        state,
        COUNT(*) AS connection_count
    FROM client_activity
    GROUP BY
        COALESCE(NULLIF(application_name, ''), '(unknown)'),
        state
)

SELECT
    'SYSTEM'::text AS record_type,

    NULL::oid AS database_oid,
    NULL::text AS database_name,

    NULL::bigint AS sessions,
    NULL::bigint AS sessions_abandoned,
    NULL::bigint AS sessions_fatal,
    NULL::bigint AS sessions_killed,

    NULL::double precision AS session_time,
    NULL::double precision AS active_time,
    NULL::double precision AS idle_in_transaction_time,

    NULL::timestamptz AS stats_reset,

    s.total_client_connections AS current_connections,
    s.active_connections,
    s.idle_connections,
    s.idle_in_transaction_connections,
    s.idle_in_transaction_aborted_connections,

    s.oldest_idle_state_change,
    s.oldest_idle_in_transaction_state_change,
    s.oldest_idle_in_transaction_aborted_state_change,

    NULL::text AS breakdown_type,
    NULL::text AS dimension_value,
    NULL::text AS state,
    NULL::bigint AS connection_count,

    c.captured_at

FROM system_activity AS s
CROSS JOIN collection_context AS c

UNION ALL

SELECT
    'DATABASE'::text AS record_type,

    d.database_oid,
    d.database_name,

    d.sessions,
    d.sessions_abandoned,
    d.sessions_fatal,
    d.sessions_killed,

    d.session_time,
    d.active_time,
    d.idle_in_transaction_time,

    d.stats_reset,

    d.current_connections,
    d.active_connections,
    d.idle_connections,
    d.idle_in_transaction_connections,
    d.idle_in_transaction_aborted_connections,

    NULL::timestamptz AS oldest_idle_state_change,
    NULL::timestamptz AS oldest_idle_in_transaction_state_change,
    NULL::timestamptz AS oldest_idle_in_transaction_aborted_state_change,

    NULL::text AS breakdown_type,
    NULL::text AS dimension_value,
    NULL::text AS state,
    NULL::bigint AS connection_count,

    c.captured_at

FROM database_stats AS d
CROSS JOIN collection_context AS c

UNION ALL

SELECT
    'BREAKDOWN'::text AS record_type,

    NULL::oid AS database_oid,
    NULL::text AS database_name,

    NULL::bigint AS sessions,
    NULL::bigint AS sessions_abandoned,
    NULL::bigint AS sessions_fatal,
    NULL::bigint AS sessions_killed,

    NULL::double precision AS session_time,
    NULL::double precision AS active_time,
    NULL::double precision AS idle_in_transaction_time,

    NULL::timestamptz AS stats_reset,

    NULL::bigint AS current_connections,
    NULL::bigint AS active_connections,
    NULL::bigint AS idle_connections,
    NULL::bigint AS idle_in_transaction_connections,
    NULL::bigint AS idle_in_transaction_aborted_connections,

    NULL::timestamptz AS oldest_idle_state_change,
    NULL::timestamptz AS oldest_idle_in_transaction_state_change,
    NULL::timestamptz AS oldest_idle_in_transaction_aborted_state_change,

    b.breakdown_type,
    b.dimension_value,
    b.state,
    b.connection_count,

    c.captured_at

FROM
(
    SELECT * FROM user_breakdown

    UNION ALL

    SELECT * FROM application_breakdown
) AS b
CROSS JOIN collection_context AS c

ORDER BY
    record_type,
    database_name,
    breakdown_type,
    dimension_value,
    state;