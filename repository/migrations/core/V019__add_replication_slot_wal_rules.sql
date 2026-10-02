/*
===============================================================================
Migration No : 019
Version      : V019
Title        : Add Replication Slot WAL Rules

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds the PostgreSQL Replication Health assessment and the initial replication
slot WAL health rules.

PG-REP-001 detects replication slots whose required WAL exceeds the normal
WAL size boundary while the WAL is still retained.

PG-REP-002 detects replication slots whose required WAL is no longer safely
retained or has already been lost.

Both rules use PG_REPLICATION_SLOTS evidence.
===============================================================================
*/


/* ============================================================================
   ASSESSMENT DEFINITION
   ============================================================================ */

INSERT INTO keystone.assessment_definition
(
    assessment_key,
    name,
    provider,
    description
)
VALUES
(
    'PG_REPLICATION_HEALTH',
    'Replication Health',
    'PostgreSQL',
    'Evaluates PostgreSQL replication health and replication-related operational risks.'
);


/* ============================================================================
   PG-REP-001 - REPLICATION SLOT WAL RETENTION PRESSURE
   ============================================================================ */

INSERT INTO keystone.rule_definition
(
    assessment_id,
    rule_key,
    name,
    description,
    evidence_source,
    default_severity,
    finding_template,
    recommendation
)
SELECT
    assessment_id,
    'PG-REP-001',
    'Replication Slot WAL Retention Pressure',
    'Detects replication slots whose required WAL exceeds the normal max_wal_size boundary while the WAL is still retained.',
    'PG_REPLICATION_SLOTS',
    'WARNING',
    'Replication slot {slot_name} has WAL status {wal_status}.',
    'Review the replication consumer and WAL retention configuration. Determine why the slot is retaining WAL beyond the normal WAL size boundary and verify that the consumer is progressing.'
FROM keystone.assessment_definition
WHERE assessment_key = 'PG_REPLICATION_HEALTH';


/* ============================================================================
   PG-REP-002 - REPLICATION SLOT WAL UNAVAILABLE
   ============================================================================ */

INSERT INTO keystone.rule_definition
(
    assessment_id,
    rule_key,
    name,
    description,
    evidence_source,
    default_severity,
    finding_template,
    recommendation
)
SELECT
    assessment_id,
    'PG-REP-002',
    'Replication Slot WAL Unavailable',
    'Detects replication slots whose required WAL is no longer safely retained or has already been lost.',
    'PG_REPLICATION_SLOTS',
    'CRITICAL',
    'Replication slot {slot_name} has WAL status {wal_status}.',
    'Investigate the replication consumer immediately. Verify whether the slot can recover or must be recreated, and review WAL retention configuration and consumer availability.'
FROM keystone.assessment_definition
WHERE assessment_key = 'PG_REPLICATION_HEALTH';


/* ============================================================================
   EVIDENCE REQUIREMENTS
   ============================================================================ */

INSERT INTO keystone.rule_evidence_requirement
(
    rule_id,
    evidence_source,
    is_required,
    max_age_seconds
)
SELECT
    rule_id,
    'PG_REPLICATION_SLOTS',
    TRUE,
    600
FROM keystone.rule_definition
WHERE rule_key IN
(
    'PG-REP-001',
    'PG-REP-002'
);