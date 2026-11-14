/*
===============================================================================
Key        : PG_QUERY_STATS
Name       : Query Statistics
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Reads pg_stat_statements when it is loaded and created in this database: the
10 statements with the most execution time and the 5 that wrote most
temporary files or read most blocks from disk, with their totals, and the
total time of all statements. A SYSTEM row says whether pg_stat_statements
is loaded, created and since when it counts.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp() AS captured_at,
        current_setting('server_version_num')::integer AS version,
        current_setting('shared_preload_libraries') ~ 'pg_stat_statements' AS preloaded,
        (SELECT n.nspname FROM pg_catalog.pg_extension e
         JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace
         WHERE e.extname = 'pg_stat_statements') AS ext_schema
),

access AS
(
    SELECT
        c.*,
        CASE WHEN c.preloaded AND c.ext_schema IS NOT NULL
             THEN has_table_privilege(format('%I.pg_stat_statements', c.ext_schema), 'SELECT')
             ELSE false
        END AS available
    FROM collection_context AS c
),

statements AS
(
    SELECT
        ((xpath('row/queryid/text()', r))[1])::text::bigint           AS queryid,
        ((xpath('row/database_name/text()', r))[1])::text             AS database_name,
        ((xpath('row/user_name/text()', r))[1])::text                 AS user_name,
        ((xpath('row/calls/text()', r))[1])::text::bigint             AS calls,
        ((xpath('row/total_ms/text()', r))[1])::text::numeric         AS total_ms,
        ((xpath('row/rows/text()', r))[1])::text::bigint              AS rows,
        ((xpath('row/shared_blks_hit/text()', r))[1])::text::bigint   AS shared_blks_hit,
        ((xpath('row/shared_blks_read/text()', r))[1])::text::bigint  AS shared_blks_read,
        ((xpath('row/temp_blks_written/text()', r))[1])::text::bigint AS temp_blks_written,
        ((xpath('row/query/text()', r))[1])::text                     AS query_text,
        ((xpath('row/all_ms/text()', r))[1])::text::numeric           AS all_ms
    FROM access AS a
    CROSS JOIN LATERAL unnest(xpath('/table/row', query_to_xml(
        CASE WHEN a.available THEN format(
            'WITH s AS (SELECT s.queryid, d.datname AS database_name, r.rolname AS user_name, s.calls, '
            '%s AS total_ms, s.rows, s.shared_blks_hit, s.shared_blks_read, s.temp_blks_written, '
            'left(s.query, 1000) AS query '
            'FROM %I.pg_stat_statements s '
            'LEFT JOIN pg_catalog.pg_database d ON d.oid = s.dbid '
            'LEFT JOIN pg_catalog.pg_roles r ON r.oid = s.userid WHERE s.queryid IS NOT NULL), '
            'ranked AS (SELECT s.*, row_number() OVER (ORDER BY total_ms DESC) AS by_time, '
            'row_number() OVER (ORDER BY temp_blks_written DESC) AS by_temp, '
            'row_number() OVER (ORDER BY shared_blks_read DESC) AS by_read FROM s) '
            'SELECT ranked.*, (SELECT sum(total_ms) FROM s) AS all_ms FROM ranked '
            'WHERE by_time <= 10 OR (by_temp <= 5 AND temp_blks_written > 0) '
            'OR (by_read <= 5 AND shared_blks_read > 0)',
            CASE WHEN a.version >= 130000 THEN 's.total_exec_time' ELSE 's.total_time' END,
            a.ext_schema)
        ELSE 'SELECT 1 AS none WHERE false' END, false, false, ''))) AS r
),

statistics_reset AS
(
    SELECT ((xpath('row/stats_reset/text()', r))[1])::text::timestamptz AS stats_reset
    FROM access AS a
    CROSS JOIN LATERAL unnest(xpath('/table/row', query_to_xml(
        CASE WHEN a.available AND a.version >= 140000
             THEN format('SELECT stats_reset FROM %I.pg_stat_statements_info', a.ext_schema)
             ELSE 'SELECT 1 AS none WHERE false' END, false, false, ''))) AS r
)

SELECT
    'SYSTEM'::text        AS record_type,
    a.preloaded,
    (a.ext_schema IS NOT NULL) AS extension_created,
    a.available,
    (SELECT stats_reset FROM statistics_reset) AS stats_reset,
    (SELECT max(all_ms) FROM statements) AS all_total_ms,
    NULL::bigint          AS queryid,
    current_database()::text AS database_name,              -- where pg_stat_statements was looked for
    NULL::text            AS user_name,
    NULL::bigint          AS calls,
    NULL::numeric         AS total_ms,
    NULL::bigint          AS rows,
    NULL::bigint          AS shared_blks_hit,
    NULL::bigint          AS shared_blks_read,
    NULL::bigint          AS temp_blks_written,
    NULL::text            AS query_text,
    a.captured_at
FROM access AS a

UNION ALL

SELECT
    'QUERY', NULL, NULL, NULL, NULL, NULL,
    s.queryid, s.database_name, s.user_name, s.calls, s.total_ms, s.rows,
    s.shared_blks_hit, s.shared_blks_read, s.temp_blks_written, s.query_text,
    a.captured_at
FROM statements AS s
CROSS JOIN access AS a

ORDER BY record_type DESC, total_ms DESC NULLS LAST;
