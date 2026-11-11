/*
===============================================================================
Key        : PG_EXTENSIONS
Name       : Extensions
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Collects the extensions created in every database with their installed
version, the version of the package on the server (default_version) and their
schema. A DATABASE row per collected database marks it as read. No internet
or release list is needed: the server's own package is the reference.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp()  AS captured_at,
        current_database() AS database_name
)

SELECT
    'DATABASE'::text AS record_type,
    c.database_name,
    NULL::text AS extension_name,
    NULL::text AS installed_version,
    NULL::text AS default_version,
    NULL::text AS schema_name,
    c.captured_at
FROM collection_context AS c

UNION ALL

SELECT
    'EXTENSION'::text,
    c.database_name,
    e.extname::text,
    e.extversion::text,
    a.default_version::text,
    n.nspname::text,
    c.captured_at
FROM pg_catalog.pg_extension AS e
JOIN pg_catalog.pg_namespace AS n
    ON n.oid = e.extnamespace
LEFT JOIN pg_catalog.pg_available_extensions AS a
    ON a.name = e.extname
CROSS JOIN collection_context AS c

ORDER BY
    record_type,
    extension_name NULLS FIRST;
