/*
===============================================================================
Key        : PG_DATABASE_INVENTORY
Name       : Database Inventory & Capacity
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Collects PostgreSQL database inventory and capacity information for historical
tracking at the logical system level.
===============================================================================
*/

WITH snapshot AS
(
    SELECT statement_timestamp() AS captured_at
)
SELECT
    d.oid                               AS database_oid,
    d.datname                           AS database_name,
    r.rolname                           AS database_owner,
    pg_encoding_to_char(d.encoding)     AS encoding,
    d.datcollate                        AS collation_name,
    d.datctype                          AS ctype_name,
    d.datconnlimit                      AS connection_limit,
    d.datallowconn                      AS allow_connections,
    d.datistemplate                     AS is_template,
    pg_database_size(d.oid)             AS database_size_bytes,
    ts.spcname                          AS tablespace_name,
    snap.captured_at                    AS captured_at
FROM pg_database d
JOIN pg_roles r
    ON r.oid = d.datdba
JOIN pg_tablespace ts
    ON ts.oid = d.dattablespace
CROSS JOIN snapshot snap
ORDER BY d.datname;