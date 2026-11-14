/*
===============================================================================
Key        : PG_HBA_RULES
Name       : Client Authentication Rules
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : NODE

Description
-----------
Collects the rules of pg_hba.conf as the server parsed them
(pg_hba_file_rules): connection type, databases, users, address and
authentication method of every line. Superuser only by default; an ACCESS
row says whether this role could read them, so a missing privilege is
reported, not failed (read through query_to_xml).
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp() AS captured_at,
        has_table_privilege('pg_catalog.pg_hba_file_rules', 'SELECT')
            AND has_function_privilege('pg_catalog.pg_hba_file_rules()', 'EXECUTE') AS readable
),

rules AS
(
    SELECT
        ((xpath('row/line_number/text()', r))[1])::text::integer AS line_number,
        ((xpath('row/type/text()', r))[1])::text                 AS conn_type,
        ((xpath('row/databases/text()', r))[1])::text            AS databases,
        ((xpath('row/users/text()', r))[1])::text                AS users,
        ((xpath('row/address/text()', r))[1])::text              AS address,
        ((xpath('row/netmask/text()', r))[1])::text              AS netmask,
        ((xpath('row/auth_method/text()', r))[1])::text          AS auth_method,
        ((xpath('row/error/text()', r))[1])::text                AS error
    FROM collection_context AS c
    CROSS JOIN LATERAL unnest(xpath('/table/row', query_to_xml(
        CASE WHEN c.readable
             THEN 'SELECT line_number, type, array_to_string(database, '','') AS databases, '
                  'array_to_string(user_name, '','') AS users, address, netmask, auth_method, error '
                  'FROM pg_catalog.pg_hba_file_rules'
             ELSE 'SELECT 1 AS none WHERE false'
        END, false, false, ''))) AS r
)

SELECT
    'ACCESS'::text   AS record_type,
    c.readable,
    NULL::integer    AS line_number,
    NULL::text       AS conn_type,
    NULL::text       AS databases,
    NULL::text       AS users,
    NULL::text       AS address,
    NULL::text       AS netmask,
    NULL::text       AS auth_method,
    NULL::text       AS error,
    c.captured_at
FROM collection_context AS c

UNION ALL

SELECT
    'RULE',
    NULL,
    r.line_number,
    r.conn_type,
    r.databases,
    r.users,
    r.address,
    r.netmask,
    r.auth_method,
    r.error,
    c.captured_at
FROM rules AS r
CROSS JOIN collection_context AS c

ORDER BY record_type, line_number NULLS FIRST;
