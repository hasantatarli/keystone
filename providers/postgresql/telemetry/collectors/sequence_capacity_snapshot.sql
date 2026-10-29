/*
===============================================================================
Key        : PG_SEQUENCE_CAPACITY
Name       : Sequence Capacity
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Collects every user sequence with its limits, the column it feeds (serial or
identity) and its last value. The last value needs SELECT or USAGE on the
sequence; without it the row says so (is_readable) instead of failing.
Sequences of extensions are left out.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp()  AS captured_at,
        current_database() AS database_name
),
sequences AS
(
    SELECT
        n.nspname::text                         AS schema_name,
        c.relname::text                         AS sequence_name,
        format_type(s.seqtypid, NULL)           AS data_type,
        s.seqmin                                AS min_value,
        s.seqmax                                AS max_value,
        s.seqincrement                          AS increment_by,
        s.seqcycle                              AS is_cycle,
        has_sequence_privilege(c.oid, 'SELECT,USAGE') AS is_readable,
        CASE WHEN has_sequence_privilege(c.oid, 'SELECT,USAGE')
             THEN pg_sequence_last_value(c.oid) END    AS last_value,
        owner_table.relname::text               AS table_name,
        owner_column.attname::text              AS column_name,
        format_type(owner_column.atttypid, owner_column.atttypmod) AS column_type
    FROM pg_catalog.pg_sequence AS s
    JOIN pg_catalog.pg_class AS c
        ON c.oid = s.seqrelid
    JOIN pg_catalog.pg_namespace AS n
        ON n.oid = c.relnamespace
    -- serial ('a') and identity ('i') sequences depend on the column they feed
    LEFT JOIN pg_catalog.pg_depend AS d
        ON d.classid = 'pg_catalog.pg_class'::regclass
       AND d.objid = c.oid
       AND d.refclassid = 'pg_catalog.pg_class'::regclass
       AND d.refobjsubid > 0
       AND d.deptype IN ('a', 'i')
    LEFT JOIN pg_catalog.pg_class AS owner_table
        ON owner_table.oid = d.refobjid
    LEFT JOIN pg_catalog.pg_attribute AS owner_column
        ON owner_column.attrelid = d.refobjid
       AND owner_column.attnum = d.refobjsubid
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_depend AS e
                      WHERE e.classid = 'pg_catalog.pg_class'::regclass
                        AND e.objid = c.oid AND e.deptype = 'e')
)
SELECT
    'DATABASE'::text AS record_type,
    c.database_name,
    NULL::text    AS schema_name,
    NULL::text    AS sequence_name,
    NULL::text    AS data_type,
    NULL::numeric AS min_value,
    NULL::numeric AS max_value,
    NULL::bigint  AS increment_by,
    NULL::boolean AS is_cycle,
    NULL::boolean AS is_readable,
    NULL::numeric AS last_value,
    NULL::text    AS table_name,
    NULL::text    AS column_name,
    NULL::text    AS column_type,
    c.captured_at
FROM collection_context AS c

UNION ALL

SELECT
    'SEQUENCE'::text,
    c.database_name,
    s.schema_name,
    s.sequence_name,
    s.data_type,
    s.min_value,
    s.max_value,
    s.increment_by,
    s.is_cycle,
    s.is_readable,
    s.last_value,
    s.table_name,
    s.column_name,
    s.column_type,
    c.captured_at
FROM sequences AS s
CROSS JOIN collection_context AS c

ORDER BY
    record_type,
    schema_name NULLS FIRST,
    sequence_name NULLS FIRST;
