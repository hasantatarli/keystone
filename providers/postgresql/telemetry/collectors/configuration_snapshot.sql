/*
===============================================================================
Key        : PG_CONFIGURATION_SNAPSHOT
Name       : Configuration Snapshot
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : NODE

Description
-----------
Collects PostgreSQL configuration settings and related metadata from
pg_settings for historical configuration tracking.
===============================================================================
*/

WITH snapshot AS
(
    SELECT clock_timestamp() AS captured_at
)
SELECT
    s.name              AS setting_name,
    s.setting           AS setting_value,
    s.unit              AS unit,
    s.vartype           AS setting_type,
    s.category          AS category,
    s.context           AS context,
    s.source            AS source,
    s.pending_restart   AS pending_restart,
    snap.captured_at    AS captured_at
FROM pg_settings s
CROSS JOIN snapshot snap
ORDER BY
    s.category,
    s.name;