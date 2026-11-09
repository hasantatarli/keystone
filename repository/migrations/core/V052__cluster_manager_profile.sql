/*
===============================================================================
Migration No : 052
Version      : V052
Title        : Cluster Manager in the Server Profile

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds how the system's settings are managed to the server profile: PATRONI
(patronictl edit-config) or NONE (ALTER SYSTEM). NULL is not given: the
report then writes both command sets as comments, never as commands to run
(review 2026-11-09: a guess must not choose the commands).
===============================================================================
*/

ALTER TABLE keystone.target
    ADD COLUMN cluster_manager VARCHAR(20),
    ADD CONSTRAINT ck_target_cluster_manager CHECK (cluster_manager IN ('PATRONI', 'NONE'));

COMMENT ON COLUMN keystone.target.cluster_manager IS
'How settings are managed: PATRONI (patronictl edit-config) or NONE (ALTER SYSTEM); NULL not given.';
