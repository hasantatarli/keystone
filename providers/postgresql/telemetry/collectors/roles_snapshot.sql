/*
===============================================================================
Key        : PG_ROLES
Name       : Roles
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Collects the roles of the cluster with their attributes (login, superuser,
createrole, createdb, replication, bypassrls). Predefined pg_* roles are left
out. Password hashes (pg_authid) are not read.
===============================================================================
*/

WITH collection_context AS
(
    SELECT clock_timestamp() AS captured_at
)
SELECT
    r.oid                  AS role_oid,
    r.rolname::text        AS role_name,
    r.rolcanlogin          AS can_login,
    r.rolsuper             AS is_superuser,
    r.rolcreaterole        AS can_create_role,
    r.rolcreatedb          AS can_create_db,
    r.rolreplication       AS is_replication,
    r.rolbypassrls         AS bypass_rls,
    r.rolvaliduntil        AS valid_until,
    c.captured_at
FROM pg_catalog.pg_roles AS r
CROSS JOIN collection_context AS c
WHERE r.rolname NOT LIKE 'pg\_%'
ORDER BY
    r.rolname;
