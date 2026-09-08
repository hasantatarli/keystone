/*
===============================================================================
Key        : PG_TRANSACTION_WRAPAROUND
Name       : Transaction ID & Wraparound
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Collects raw PostgreSQL transaction ID and MultiXact freeze horizon information
at database and relation level for wraparound monitoring.
===============================================================================
*/

WITH database_info AS
(
    SELECT
        d.oid                                      AS database_oid,
        d.datname                                  AS database_name,
        d.datfrozenxid                             AS frozen_xid,
        age(d.datfrozenxid)::bigint                AS xid_age,
        d.datminmxid                               AS min_mxid,
        mxid_age(d.datminmxid)::bigint             AS mxid_age
    FROM pg_catalog.pg_database AS d
    WHERE d.datname = current_database()
),
relation_info AS
(
    SELECT
        d.oid                                      AS database_oid,
        d.datname                                  AS database_name,
        n.nspname                                  AS schema_name,
        c.oid                                      AS object_oid,
        c.relname                                  AS object_name,
        c.relispartition                           AS is_partition,
        c.relfrozenxid                             AS frozen_xid,
        age(c.relfrozenxid)::bigint                AS xid_age,
        c.relminmxid                               AS min_mxid,
        mxid_age(c.relminmxid)::bigint             AS mxid_age
    FROM pg_catalog.pg_class AS c
    INNER JOIN pg_catalog.pg_namespace AS n
        ON n.oid = c.relnamespace
    CROSS JOIN pg_catalog.pg_database AS d
    WHERE d.datname = current_database()
      AND c.relkind IN ('r', 'm')
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname !~ '^pg_toast'
)
SELECT
    'DATABASE'::text                               AS record_type,
    database_oid,
    database_name,
    NULL::text                                     AS schema_name,
    NULL::oid                                      AS object_oid,
    NULL::text                                     AS object_name,
    NULL::boolean                                  AS is_partition,
    frozen_xid,
    xid_age,
    min_mxid,
    mxid_age,
    clock_timestamp()                              AS captured_at
FROM database_info

UNION ALL

SELECT
    'RELATION'::text                               AS record_type,
    database_oid,
    database_name,
    schema_name,
    object_oid,
    object_name,
    is_partition,
    frozen_xid,
    xid_age,
    min_mxid,
    mxid_age,
    clock_timestamp()                              AS captured_at
FROM relation_info

ORDER BY
    record_type,
    schema_name NULLS FIRST,
    object_name NULLS FIRST;