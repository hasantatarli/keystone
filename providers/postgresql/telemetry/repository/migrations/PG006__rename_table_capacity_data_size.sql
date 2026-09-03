/*
===============================================================================
Migration No : 006
Version      : PG006
Title        : Rename Table Capacity Data Size

Author       : Hasan Tatarlı
Applies To   : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Renames table_size_bytes to data_size_bytes to distinguish base table data
storage from the total physical size of the logical database object.
===============================================================================
*/

ALTER TABLE postgresql.table_capacity_snapshot
    RENAME COLUMN table_size_bytes TO data_size_bytes;