/*
===============================================================================
Migration No : 046
Version      : V046
Title        : Target Server Profile

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
ADR-0017 step 1: facts Keystone cannot collect, recorded on the target the
health check runs on (a SYSTEM, or a NODE without a SYSTEM). NULL means "not
given"; the default is chosen in code and the report says it was assumed.
Each health check keeps the profile it used, so old reports stay correct.
===============================================================================
*/

ALTER TABLE keystone.target
    ADD COLUMN workload_type VARCHAR(10),
    ADD COLUMN dedicated     BOOLEAN,
    ADD COLUMN storage_type  VARCHAR(10),
    ADD CONSTRAINT ck_target_workload_type CHECK (workload_type IN ('OLTP', 'OLAP', 'MIXED')),
    ADD CONSTRAINT ck_target_storage_type  CHECK (storage_type IN ('SSD', 'HDD'));

COMMENT ON COLUMN keystone.target.workload_type IS
'OLTP, OLAP (reporting) or MIXED; NULL: not given, OLTP assumed (ADR-0017).';
COMMENT ON COLUMN keystone.target.dedicated IS
'Server dedicated to PostgreSQL; NULL: not given, dedicated assumed (ADR-0017).';
COMMENT ON COLUMN keystone.target.storage_type IS
'SSD or HDD; NULL: not given, SSD assumed (ADR-0017).';

ALTER TABLE keystone.health_check
    ADD COLUMN target_profile JSONB;

COMMENT ON COLUMN keystone.health_check.target_profile IS
'Server profile used by this check: {field: {"value": ..., "assumed": bool}}.';
