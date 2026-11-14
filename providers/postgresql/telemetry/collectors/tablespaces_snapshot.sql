/*
===============================================================================
Key        : PG_TABLESPACES
Name       : Tablespaces
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : NODE

Description
-----------
Collects every tablespace with its directory and size. pg_default and
pg_global live inside the data directory (empty location); others are
directories elsewhere, often on their own disk. Size needs CREATE on the
tablespace or pg_read_all_stats (in pg_monitor); otherwise it stays empty.
===============================================================================
*/

WITH collection_context AS
(
    SELECT clock_timestamp() AS captured_at
)

SELECT
    c.captured_at,
    ts.spcname                                       AS tablespace_name,
    NULLIF(pg_tablespace_location(ts.oid), '')       AS location,
    CASE
        WHEN has_tablespace_privilege(ts.oid, 'CREATE')
          OR pg_has_role('pg_read_all_stats', 'MEMBER')
        THEN pg_tablespace_size(ts.oid)
    END                                              AS size_bytes
FROM collection_context AS c
CROSS JOIN pg_tablespace AS ts
ORDER BY ts.spcname;
