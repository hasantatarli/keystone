/*
===============================================================================
Key        : PG_INSTANCE_INVENTORY
Name       : Instance Inventory
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : NODE

Description
-----------
Collects current PostgreSQL instance identity and state information.
===============================================================================
*/

SELECT
    current_setting('server_version')              AS server_version,
    current_setting('server_version_num')::INTEGER AS server_version_num,
    host(inet_server_addr())                       AS server_address,
    inet_server_port()                             AS server_port,
    current_database()                             AS current_database,
    current_user                                   AS collector_user,
    pg_is_in_recovery()                            AS in_recovery,
    pg_postmaster_start_time()                     AS postmaster_start_time,
    system_identifier::TEXT                        AS system_identifier,
    clock_timestamp()                              AS collected_at
FROM pg_control_system();

