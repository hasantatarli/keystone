/*
===============================================================================
Migration No : 033
Version      : V033
Title        : Replication Lag Beyond Intended Apply Delay

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
PG-REP-003 judges the replay lag beyond a replica's recovery_min_apply_delay.
Adds node configuration and instance inventory as optional evidence: without
them the full lag is judged.
===============================================================================
*/


/*
Design notes (2026-10-21, lab)
------------------------------
A replica delayed on purpose (recovery_min_apply_delay = 5min) was reported
as lagging. Some companies keep such a replica to recover from accidental
deletes; its delay is expected. The delay is read per node from the
configuration snapshot and the replica is matched by address through the
instance inventory. Optional evidence that is missing or stale is treated as
absent.

In the same test, pg_wal_replay_pause() could not be used to create lag:
Patroni resumes paused replay on replicas within seconds.
===============================================================================
*/

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, r.evidence_source, FALSE, r.max_age_seconds
FROM keystone.rule_definition rd
CROSS JOIN (VALUES
    ('PG_CONFIGURATION_SNAPSHOT', 86400),
    ('PG_INSTANCE_INVENTORY',     3600)
) AS r (evidence_source, max_age_seconds)
WHERE rd.rule_key = 'PG-REP-003'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

UPDATE keystone.rule_definition
SET description = 'Detects replicas that replay changes later than the configured thresholds, beyond any intended apply delay (recovery_min_apply_delay).',
    finding_template = 'Replica {replica} is {lag_seconds} seconds behind the primary in replaying changes, beyond any intended apply delay.'
WHERE rule_key = 'PG-REP-003';
