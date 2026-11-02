/*
===============================================================================
Key        : PG_CHECKPOINT_STATS
Name       : Checkpoint Statistics
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Checkpoints done since the statistics were reset: timed ones (checkpoint_timeout)
and requested ones (mostly WAL reaching max_wal_size). PostgreSQL 17 moved
these counters from pg_stat_bgwriter to pg_stat_checkpointer; the view that
exists is chosen by version and read through query_to_xml, so one script
runs on every supported version.
===============================================================================
*/

WITH source AS
(
    SELECT query_to_xml(
        CASE WHEN current_setting('server_version_num')::integer >= 170000
             THEN 'SELECT num_timed AS timed, num_requested AS requested, stats_reset '
                  'FROM pg_catalog.pg_stat_checkpointer'
             ELSE 'SELECT checkpoints_timed AS timed, checkpoints_req AS requested, stats_reset '
                  'FROM pg_catalog.pg_stat_bgwriter'
        END, false, false, '') AS doc
)
SELECT
    pg_catalog.pg_is_in_recovery()                                              AS in_recovery,
    ((xpath('/table/row/timed/text()', s.doc))[1])::text::bigint                AS checkpoints_timed,
    ((xpath('/table/row/requested/text()', s.doc))[1])::text::bigint            AS checkpoints_requested,
    ((xpath('/table/row/stats_reset/text()', s.doc))[1])::text::timestamptz     AS stats_reset,
    clock_timestamp()                                                           AS captured_at
FROM source AS s;
