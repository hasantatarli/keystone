/*
===============================================================================
Key        : PG_TABLE_STRUCTURE
Name       : Table Structure
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Collects foreign keys with their columns, the referencing table's size and
whether an index starts with the key's columns, and unlogged tables, in every
database. A DATABASE row per collected database marks it as read even when it
has neither. Objects of extensions are marked extension_owned.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp()  AS captured_at,
        current_database() AS database_name
),

extension_objects AS
(
    SELECT d.objid
    FROM pg_catalog.pg_depend AS d
    WHERE d.classid = 'pg_catalog.pg_class'::regclass
      AND d.deptype = 'e'
),

-- A partitioned table has no data of its own; its size is that of its partitions.
table_size AS
(
    SELECT
        c.oid,
        CASE WHEN c.relkind = 'p'
             THEN (SELECT COALESCE(sum(pg_relation_size(i.inhrelid)), 0)
                   FROM pg_catalog.pg_inherits AS i WHERE i.inhparent = c.oid)
             ELSE pg_relation_size(c.oid)
        END::bigint AS size_bytes
    FROM pg_catalog.pg_class AS c
    WHERE c.relkind IN ('r', 'p')
)

SELECT
    'DATABASE'::text AS record_type,
    c.database_name,
    NULL::text    AS schema_name,
    NULL::text    AS table_name,
    NULL::text    AS constraint_name,
    NULL::text    AS key_columns,
    NULL::text    AS referenced_table,
    NULL::boolean AS has_index,
    NULL::bigint  AS table_size_bytes,
    NULL::boolean AS extension_owned,
    c.captured_at
FROM collection_context AS c

UNION ALL

-- Foreign keys of the table itself; keys inherited by partitions are left to the parent.
SELECT
    'FOREIGN_KEY'::text,
    cc.database_name,
    n.nspname::text,
    t.relname::text,
    con.conname::text,
    (SELECT string_agg(a.attname::text, ', ' ORDER BY k.ord)
     FROM unnest(con.conkey) WITH ORDINALITY AS k (attnum, ord)
     JOIN pg_catalog.pg_attribute AS a
       ON a.attrelid = con.conrelid AND a.attnum = k.attnum),
    (SELECT rn.nspname || '.' || rc.relname
     FROM pg_catalog.pg_class AS rc
     JOIN pg_catalog.pg_namespace AS rn ON rn.oid = rc.relnamespace
     WHERE rc.oid = con.confrelid),
    -- An index whose first columns are exactly the key's columns, in any order.
    EXISTS (SELECT 1
            FROM pg_catalog.pg_index AS i
            WHERE i.indrelid = con.conrelid
              AND i.indisvalid
              AND i.indpred IS NULL
              AND (string_to_array(i.indkey::text, ' ')::smallint[])[1:cardinality(con.conkey)]
                  @> con.conkey
              AND (string_to_array(i.indkey::text, ' ')::smallint[])[1:cardinality(con.conkey)]
                  <@ con.conkey),
    ts.size_bytes,
    con.conrelid IN (SELECT objid FROM extension_objects),
    cc.captured_at
FROM pg_catalog.pg_constraint AS con
JOIN pg_catalog.pg_class AS t
    ON t.oid = con.conrelid
JOIN pg_catalog.pg_namespace AS n
    ON n.oid = t.relnamespace
LEFT JOIN table_size AS ts
    ON ts.oid = con.conrelid
CROSS JOIN collection_context AS cc
WHERE con.contype = 'f'
  AND con.conparentid = 0
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')

UNION ALL

SELECT
    'UNLOGGED_TABLE'::text,
    cc.database_name,
    n.nspname::text,
    t.relname::text,
    NULL::text,
    NULL::text,
    NULL::text,
    NULL::boolean,
    pg_total_relation_size(t.oid),
    t.oid IN (SELECT objid FROM extension_objects),
    cc.captured_at
FROM pg_catalog.pg_class AS t
JOIN pg_catalog.pg_namespace AS n
    ON n.oid = t.relnamespace
CROSS JOIN collection_context AS cc
WHERE t.relpersistence = 'u'
  AND t.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')

ORDER BY
    record_type,
    schema_name NULLS FIRST,
    table_name NULLS FIRST,
    constraint_name NULLS FIRST;
