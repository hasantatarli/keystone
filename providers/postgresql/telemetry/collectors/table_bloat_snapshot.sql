/*
===============================================================================
Key        : PG_TABLE_BLOAT
Name       : Table and Index Bloat
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Estimates wasted space in tables and btree indexes of at least 100 MB. With
pgstattuple: pgstattuple_approx for tables. Otherwise from pg_stats column
widths (needs SELECT on the table). An object neither can measure comes with
method NULL. A DATABASE row says which methods were available.
===============================================================================
*/

WITH
collection_context AS
(
    SELECT
        clock_timestamp() AS captured_at,
        current_setting('block_size')::numeric AS bs,
        (SELECT format('%I.pgstattuple_approx(%%s::oid::regclass)', n.nspname)
         FROM pg_catalog.pg_extension e
         JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace
         JOIN pg_catalog.pg_proc p ON p.proname = 'pgstattuple_approx' AND p.pronamespace = n.oid
         WHERE e.extname = 'pgstattuple'
           AND has_function_privilege(p.oid, 'EXECUTE')
         LIMIT 1) AS approx_call
),

objects AS
(
    SELECT
        c.oid,
        c.relkind,
        n.nspname::text AS schema_name,
        c.relname::text AS object_name,
        CASE WHEN c.relkind = 'i' THEN tc.relname::text END AS table_name,
        c.relpages::numeric * x.bs AS size_bytes,
        c.reltuples,
        c.relpages,
        coalesce((SELECT split_part(o, '=', 2)::numeric FROM unnest(c.reloptions) o
                  WHERE o LIKE 'fillfactor=%'), CASE WHEN c.relkind = 'i' THEN 90 ELSE 100 END) AS fillfactor,
        i.indrelid,
        i.indkey
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN collection_context x
    LEFT JOIN pg_catalog.pg_index i ON i.indexrelid = c.oid
    LEFT JOIN pg_catalog.pg_class tc ON tc.oid = i.indrelid
    LEFT JOIN pg_catalog.pg_am am ON am.oid = c.relam
    WHERE c.relkind IN ('r', 'm', 'i')
      AND (c.relkind <> 'i' OR am.amname = 'btree')
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname !~ '^pg_toast'
      AND c.relpages::numeric * x.bs >= 104857600
),

-- Column statistics per object: for a table its columns, for an index its plain key columns.
columns AS
(
    SELECT o.oid, a.attname, s.avg_width, s.null_frac
    FROM objects o
    JOIN pg_catalog.pg_attribute a
        ON a.attrelid = CASE WHEN o.relkind = 'i' THEN o.indrelid ELSE o.oid END
       AND a.attnum > 0 AND NOT a.attisdropped
       AND (o.relkind <> 'i' OR a.attnum = ANY (o.indkey::smallint[]))
    LEFT JOIN pg_catalog.pg_stats s
        ON s.schemaname = (SELECT nspname FROM pg_catalog.pg_namespace WHERE oid =
                            (SELECT relnamespace FROM pg_catalog.pg_class WHERE oid = a.attrelid))
       AND s.tablename = (SELECT relname FROM pg_catalog.pg_class WHERE oid = a.attrelid)
       AND s.attname = a.attname
),

statistics_estimate AS
(
    SELECT
        o.oid,
        CASE WHEN o.relkind = 'i' THEN
            -- btree leaf pages: (index tuple header 8 + key data) aligned, + 4 for the line pointer
            ceil(o.reltuples / greatest(floor((x.bs - 24 - 16) * o.fillfactor / 100
                / (8 + ceil(sum((1 - c.null_frac) * c.avg_width) / 8) * 8 + 4)), 1))
        ELSE
            -- heap pages: (tuple header 23 + null bitmap) aligned + data aligned, + 4 for the line pointer
            ceil(o.reltuples / greatest(floor((x.bs - 24) * o.fillfactor / 100
                / (ceil((23 + CASE WHEN max(c.null_frac) > 0 THEN ceil(count(*) / 8.0) ELSE 0 END) / 8) * 8
                   + ceil(sum((1 - c.null_frac) * c.avg_width) / 8) * 8 + 4)), 1))
        END AS expected_pages
    FROM objects o
    JOIN columns c ON c.oid = o.oid
    CROSS JOIN collection_context x
    WHERE o.reltuples > 0
      AND NOT (o.relkind = 'i' AND 0 = ANY (o.indkey::smallint[]))       -- expression index: no stats
    GROUP BY o.oid, o.relkind, o.reltuples, o.fillfactor, x.bs
    HAVING count(c.avg_width) = count(*)                                   -- every column has stats
),

approx AS
(
    SELECT
        ((xpath('row/relid/text()', r))[1])::text::oid                 AS oid,
        ((xpath('row/dead_tuple_len/text()', r))[1])::text::numeric     AS dead_tuple_len,
        ((xpath('row/approx_free_space/text()', r))[1])::text::numeric  AS free_space
    FROM collection_context x
    CROSS JOIN LATERAL unnest(xpath('/table/row', query_to_xml(
        CASE WHEN x.approx_call IS NULL
             THEN 'SELECT 1 AS none WHERE false'
             ELSE coalesce((SELECT string_agg(format('SELECT %s AS relid, dead_tuple_len, approx_free_space FROM '
                                                     || format(x.approx_call, o.oid), o.oid), ' UNION ALL ')
                            FROM objects o WHERE o.relkind = 'r'), 'SELECT 1 AS none WHERE false')
        END, false, false, ''))) AS r
)

SELECT
    'DATABASE'::text   AS record_type,
    current_database() AS database_name,
    NULL::text         AS object_kind,
    NULL::text         AS schema_name,
    NULL::text         AS object_name,
    NULL::text         AS table_name,
    NULL::bigint       AS size_bytes,
    NULL::bigint       AS wasted_bytes,
    (x.approx_call IS NOT NULL) AS pgstattuple_available,
    NULL::text         AS method,
    x.captured_at
FROM collection_context x

UNION ALL

SELECT
    'OBJECT',
    current_database(),
    CASE WHEN o.relkind = 'i' THEN 'INDEX' ELSE 'TABLE' END,
    o.schema_name,
    o.object_name,
    o.table_name,
    o.size_bytes::bigint,
    CASE
        WHEN a.oid IS NOT NULL THEN (a.dead_tuple_len + a.free_space)::bigint
        WHEN e.oid IS NOT NULL THEN (greatest(o.relpages - e.expected_pages, 0) * x.bs)::bigint
    END,
    NULL,
    CASE WHEN a.oid IS NOT NULL THEN 'PGSTATTUPLE' WHEN e.oid IS NOT NULL THEN 'STATISTICS' END,
    x.captured_at
FROM objects o
CROSS JOIN collection_context x
LEFT JOIN approx a ON a.oid = o.oid
LEFT JOIN statistics_estimate e ON e.oid = o.oid

ORDER BY record_type, schema_name NULLS FIRST, object_name NULLS FIRST;
