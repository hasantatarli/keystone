/*
===============================================================================
Key        : PG_INDEX_USAGE
Name       : Index Usage
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : NODE_DATABASE

Description
-----------
Collects every user index with its scan count, size, validity and constraint,
in every database of every node: scan counts are kept per server, so an index
unused on the primary may be used by reports on a replica. Indexes of
extensions (TimescaleDB, PostGIS...) are marked extension_owned.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp()  AS captured_at,
        current_database() AS database_name
)
SELECT
    'DATABASE'::text                                         AS record_type,
    c.database_name,
    pg_is_in_recovery()                                      AS in_recovery,
    COALESCE(d.stats_reset, pg_postmaster_start_time())      AS stats_since,
    d.stats_reset IS NULL                                    AS stats_since_start,
    NULL::text    AS schema_name,
    NULL::text    AS table_name,
    NULL::text    AS index_name,
    NULL::bigint  AS idx_scan,
    NULL::bigint  AS index_size_bytes,
    NULL::boolean AS is_valid,
    NULL::boolean AS is_unique,
    NULL::text    AS constraint_type,
    NULL::boolean AS being_built,
    NULL::boolean AS extension_owned,
    c.captured_at
FROM collection_context AS c
LEFT JOIN pg_catalog.pg_stat_database AS d
    ON d.datname = c.database_name

UNION ALL

SELECT
    'INDEX'::text,
    c.database_name,
    NULL::boolean,
    NULL::timestamptz,
    NULL::boolean,
    s.schemaname::text,
    s.relname::text,
    s.indexrelname::text,
    s.idx_scan,
    pg_relation_size(s.indexrelid),
    i.indisvalid,
    i.indisunique,
    con.contype::text,
    p.index_relid IS NOT NULL,          -- CREATE INDEX CONCURRENTLY still running
    EXISTS (SELECT 1 FROM pg_catalog.pg_depend AS d
            WHERE d.classid = 'pg_catalog.pg_class'::regclass
              AND d.objid IN (s.indexrelid, s.relid)
              AND d.deptype = 'e'),
    c.captured_at
FROM pg_catalog.pg_stat_user_indexes AS s
JOIN pg_catalog.pg_index AS i
    ON i.indexrelid = s.indexrelid
LEFT JOIN pg_catalog.pg_constraint AS con
    ON con.conindid = s.indexrelid
   AND con.contype IN ('p', 'u', 'x')
LEFT JOIN pg_catalog.pg_stat_progress_create_index AS p
    ON p.index_relid = s.indexrelid
CROSS JOIN collection_context AS c

ORDER BY
    record_type,
    schema_name NULLS FIRST,
    index_name NULLS FIRST;
