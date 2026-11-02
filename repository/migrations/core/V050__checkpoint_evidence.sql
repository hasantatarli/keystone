/*
===============================================================================
Migration No : 050
Version      : V050
Title        : Checkpoint Evidence for max_wal_size

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
ADR-0017 step 3b: PG-CONF-003 reads PG_CHECKPOINT_STATS (PG020, optional).
When enough checkpoints were counted over long enough and too many were
requested (WAL reached max_wal_size), max_wal_size is recommended at a multiple
of its current value instead of the workload value.
===============================================================================
*/

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rule_id, 'PG_CHECKPOINT_STATS', FALSE, 86400
FROM keystone.rule_definition WHERE rule_key = 'PG-CONF-003'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.config_parameter
    (provider, setting_key, parameter_key, workload_type, storage_type, value_numeric, value_text, unit, description)
VALUES
('PostgreSQL', 'max_wal_size', 'requested_share_limit', NULL, NULL, 0.2, NULL, 'RATIO',
 'More requested checkpoints than this share: max_wal_size is too small.'),
('PostgreSQL', 'max_wal_size', 'min_checkpoints', NULL, NULL, 20, NULL, 'COUNT',
 'Fewer checkpoints since the statistics reset are not judged.'),
('PostgreSQL', 'max_wal_size', 'min_statistics_age', NULL, NULL, 86400, NULL, 'SECOND',
 'Statistics younger than this are not judged.'),
('PostgreSQL', 'max_wal_size', 'evidence_factor', NULL, NULL, 2, NULL, 'NUMBER',
 'Recommended max_wal_size: current value times this, still capped by the data disk.');
