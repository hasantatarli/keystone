/*
===============================================================================
Migration No : 018
Version      : V018
Title        : Add Database XID Wraparound Rule

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds the PostgreSQL database transaction ID wraparound risk rule.

The rule evaluates database-level transaction ID age using
PG_TRANSACTION_WRAPAROUND evidence and produces WARNING or CRITICAL findings
when configured thresholds are exceeded.
===============================================================================
*/


/* ============================================================================
   RULE DEFINITION
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
    'PG-TRAN-002',
    'Database Transaction ID Wraparound Risk',
    'Detects PostgreSQL databases whose transaction ID age is approaching the wraparound safety limit.',
    'PG_TRANSACTION_WRAPAROUND',
    NULL,
    'Database {database_name} has a transaction ID age of {xid_age}.',
    'Investigate transaction ID freeze progress and vacuum activity. Ensure that VACUUM can advance the database freeze horizon before transaction ID wraparound becomes a risk.'
FROM keystone.assessment_definition
WHERE assessment_key = 'PG_TRANSACTION_HEALTH';


/* ============================================================================
   RULE THRESHOLDS
   ============================================================================ */

INSERT INTO keystone.rule_threshold
(
    rule_id,
    severity,
    threshold_value,
    threshold_unit
)
SELECT
    rule_id,
    'WARNING',
    1500000000,
    'TRANSACTION'
FROM keystone.rule_definition
WHERE rule_key = 'PG-TRAN-002';


INSERT INTO keystone.rule_threshold
(
    rule_id,
    severity,
    threshold_value,
    threshold_unit
)
SELECT
    rule_id,
    'CRITICAL',
    1800000000,
    'TRANSACTION'
FROM keystone.rule_definition
WHERE rule_key = 'PG-TRAN-002';


/* ============================================================================
   EVIDENCE REQUIREMENT
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
    'PG_TRANSACTION_WRAPAROUND',
    TRUE,
    86400
FROM keystone.rule_definition
WHERE rule_key = 'PG-TRAN-002';