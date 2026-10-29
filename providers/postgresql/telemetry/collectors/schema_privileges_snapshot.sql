/*
===============================================================================
Key        : PG_SCHEMA_PRIVILEGES
Name       : Schema Privileges
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Collects, for every user schema, whether PUBLIC (every role) may use it or
create objects in it. A missing ACL means the default: owner only.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp()  AS captured_at,
        current_database() AS database_name
),
schemas AS
(
    SELECT
        n.nspname::text                AS schema_name,
        pg_get_userbyid(n.nspowner)    AS schema_owner,
        EXISTS (SELECT 1 FROM aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) AS a
                WHERE a.grantee = 0 AND a.privilege_type = 'USAGE')  AS public_usage,
        EXISTS (SELECT 1 FROM aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) AS a
                WHERE a.grantee = 0 AND a.privilege_type = 'CREATE') AS public_create
    FROM pg_catalog.pg_namespace AS n
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname NOT LIKE 'pg\_toast%'
      AND n.nspname NOT LIKE 'pg\_temp\_%'
)
SELECT
    'DATABASE'::text AS record_type,
    c.database_name,
    NULL::text       AS schema_name,
    NULL::text       AS schema_owner,
    NULL::boolean    AS public_usage,
    NULL::boolean    AS public_create,
    c.captured_at
FROM collection_context AS c

UNION ALL

SELECT
    'SCHEMA'::text,
    c.database_name,
    s.schema_name,
    s.schema_owner,
    s.public_usage,
    s.public_create,
    c.captured_at
FROM schemas AS s
CROSS JOIN collection_context AS c

ORDER BY
    record_type,
    schema_name NULLS FIRST;
