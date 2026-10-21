/*
===============================================================================
Migration No    : 014
Version         : PG014
Title           : Synchronous Standby Names in Replication Status

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Stores the primary's synchronous_standby_names with each replication status
snapshot, so synchronous replication safety (PG-REP-006) is judged from the
setting and the replica states captured at the same moment on the same server.
===============================================================================
*/

ALTER TABLE postgresql.replication_status_snapshot
    ADD COLUMN synchronous_standby_names TEXT;

COMMENT ON COLUMN postgresql.replication_status_snapshot.synchronous_standby_names IS
'synchronous_standby_names on the server the snapshot was taken from; empty means asynchronous replication. NULL for snapshots before PG014.';
