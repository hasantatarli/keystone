/*
===============================================================================
Key        : PG_PREPARED_TRANSACTIONS
Name       : Prepared Transactions
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Collects two-phase commit transactions waiting for COMMIT PREPARED or
ROLLBACK PREPARED. The SYSTEM row is always returned, so "none" is evidence.
===============================================================================
*/

WITH collection_context AS
(
    SELECT
        clock_timestamp() AS captured_at,
        current_setting('max_prepared_transactions')::integer AS max_prepared_transactions
)
SELECT
    'SYSTEM'::text         AS record_type,
    c.max_prepared_transactions,
    (SELECT count(*) FROM pg_catalog.pg_prepared_xacts)::bigint AS prepared_count,
    NULL::xid              AS transaction_id,
    NULL::text             AS gid,
    NULL::timestamptz      AS prepared_at,
    NULL::text             AS owner,
    NULL::text             AS database_name,
    c.captured_at
FROM collection_context AS c

UNION ALL

SELECT
    'TRANSACTION'::text,
    NULL::integer,
    NULL::bigint,
    p.transaction,
    p.gid,
    p.prepared,
    p.owner::text,
    p.database::text,
    c.captured_at
FROM pg_catalog.pg_prepared_xacts AS p
CROSS JOIN collection_context AS c

ORDER BY
    record_type,
    prepared_at NULLS FIRST;
