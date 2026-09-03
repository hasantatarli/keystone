/*
===============================================================================
Migration No : 005
Version      : V005
Title        : Add Target OS Type

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Adds operating system information to Keystone targets.

OS information belongs to the database-centric target model and may later
be used to determine how host-level inventory such as CPU, memory and storage
information will be collected.
===============================================================================
*/

ALTER TABLE keystone.target
ADD COLUMN os_type VARCHAR(30);