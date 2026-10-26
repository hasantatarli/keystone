/*
===============================================================================
Key        : PG_WAL_STATUS
Name       : WAL Status
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : NODE

Description
-----------
Collects WAL archiver statistics and, on a primary, the current timeline and
the modification time of its history file in pg_wal (when the server was
promoted). pg_ls_waldir() needs pg_monitor.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp()   AS captured_at,
        pg_is_in_recovery() AS in_recovery
),
timeline AS
(
    -- The first 8 hex digits of the current WAL file name are the timeline.
    SELECT
        CASE WHEN c.in_recovery THEN NULL
             ELSE ('x' || substr(pg_walfile_name(pg_current_wal_lsn()), 1, 8))::bit(32)::integer
        END AS timeline_id
    FROM collection_context AS c
)
SELECT
    c.captured_at,
    c.in_recovery,
    current_setting('archive_mode') AS archive_mode,
    tl.timeline_id,
    h.name                          AS timeline_history_file,
    h.modification                  AS timeline_started_at,
    a.archived_count,
    a.last_archived_wal,
    a.last_archived_time,
    a.failed_count,
    a.last_failed_wal,
    a.last_failed_time,
    a.stats_reset
FROM collection_context AS c
CROSS JOIN timeline AS tl
CROSS JOIN pg_catalog.pg_stat_archiver AS a
LEFT JOIN LATERAL
(
    SELECT w.name, w.modification
    FROM pg_catalog.pg_ls_waldir() AS w
    WHERE w.name = lpad(upper(to_hex(tl.timeline_id)), 8, '0') || '.history'
) AS h
    ON TRUE;
