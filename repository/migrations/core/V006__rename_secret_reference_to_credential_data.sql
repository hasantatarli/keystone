/*
===============================================================================
Migration No : 006
Version      : V006
Title        : Rename Secret Reference To Credential Data

Author       : Hasan Tatarlı
Applies To   : PostgreSQL

Description
-----------
Renames target_connection.secret_reference to credential_data.

credential_data contains authentication data according to auth_type.

Examples:
  PASSWORD   -> encrypted password
  VAULT      -> vault secret reference/path
  INTEGRATED -> NULL
===============================================================================
*/

ALTER TABLE keystone.target_connection
RENAME COLUMN secret_reference TO credential_data;