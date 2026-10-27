/*
===============================================================================
Migration No    : 017
Version         : PG017
Title           : Extension-Owned Indexes in Index Usage

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : NODE_DATABASE

Description
-----------
Marks indexes that belong to an extension (the index or its table is an
extension member), so index rules leave them out: they are not the DBA's to
drop (lab 2026-10-27: TimescaleDB catalog indexes reported as unused).
===============================================================================
*/

ALTER TABLE postgresql.index_usage_snapshot
    ADD COLUMN extension_owned BOOLEAN;

COMMENT ON COLUMN postgresql.index_usage_snapshot.extension_owned IS
'INDEX rows: the index or its table is a member of an extension (pg_depend deptype e). NULL before PG017.';
