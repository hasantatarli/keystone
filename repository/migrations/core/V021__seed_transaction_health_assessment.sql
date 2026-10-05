/*
===============================================================================
Migration No : 021
Version      : V021
Title        : Seed Transaction Health Assessment

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Idempotently seeds the PG_TRANSACTION_HEALTH assessment with PG-TRAN-001 and
PG-TRAN-002, including thresholds and evidence requirements, so that a clean
install produces the same Dictionary as the development repository.
===============================================================================
*/


/*
Why this migration exists
-------------------------
(Kept outside the header: the installer stores the header Description in
keystone.migration_history, which is limited to 500 characters.)

The PG_TRANSACTION_HEALTH assessment and the PG-TRAN-001 rule were inserted
manually into the development repository after V016 and were never added to a
migration. V017 (PG-TRAN-001 evidence requirement) and V018 (PG-TRAN-002) both
depend on those manual rows. On a clean install they therefore inserted zero
rows while still completing successfully, leaving Transaction Health missing.

Applied migrations are immutable, so V016-V018 are not edited. Instead this
migration creates every missing row idempotently:
- clean install       : creates the full Transaction Health Dictionary
- existing repository : rows already exist, every insert is a no-op

PG-TRAN-002 values intentionally repeat V018. V018 remains the historical
record; this migration guarantees the same end state on a clean install.

Existing rows are never updated. Values tuned in an existing repository are
preserved.
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
    'PG_TRANSACTION_HEALTH',
    'Transaction Health',
    'PostgreSQL',
    'Evaluates PostgreSQL transaction and session activity for conditions that may affect database health, reliability, and performance.'
)
ON CONFLICT (assessment_key) DO NOTHING;


/* ============================================================================
   PG-TRAN-001 - LONG IDLE TRANSACTION
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
    'PG-TRAN-001',
    'Long Idle Transaction',
    'Detects sessions that remain idle while a transaction is still open beyond the configured thresholds.',
    'PG_ACTIVITY_SNAPSHOT',
    NULL,
    'Session {pid} has been idle in transaction for {duration_seconds} seconds.',
    'Review the application transaction lifecycle and determine why the transaction remains open. Long idle transactions may retain resources and interfere with normal database maintenance.'
FROM keystone.assessment_definition
WHERE assessment_key = 'PG_TRANSACTION_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;


INSERT INTO keystone.rule_threshold
(
    rule_id,
    severity,
    threshold_value,
    threshold_unit
)
SELECT
    rd.rule_id,
    t.severity,
    t.threshold_value,
    t.threshold_unit
FROM keystone.rule_definition AS rd
CROSS JOIN
(
    VALUES
        ('WARNING',  300, 'SECOND'),
        ('CRITICAL', 900, 'SECOND')
) AS t (severity, threshold_value, threshold_unit)
WHERE rd.rule_key = 'PG-TRAN-001'
ON CONFLICT (rule_id, severity) DO NOTHING;


INSERT INTO keystone.rule_evidence_requirement
(
    rule_id,
    evidence_source,
    is_required,
    max_age_seconds
)
SELECT
    rule_id,
    'PG_ACTIVITY_SNAPSHOT',
    TRUE,
    600
FROM keystone.rule_definition
WHERE rule_key = 'PG-TRAN-001'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;


/* ============================================================================
   PG-TRAN-002 - DATABASE TRANSACTION ID WRAPAROUND RISK
   Same values as V018; see the description above.
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
WHERE assessment_key = 'PG_TRANSACTION_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;


INSERT INTO keystone.rule_threshold
(
    rule_id,
    severity,
    threshold_value,
    threshold_unit
)
SELECT
    rd.rule_id,
    t.severity,
    t.threshold_value,
    t.threshold_unit
FROM keystone.rule_definition AS rd
CROSS JOIN
(
    VALUES
        ('WARNING',  1500000000, 'TRANSACTION'),
        ('CRITICAL', 1800000000, 'TRANSACTION')
) AS t (severity, threshold_value, threshold_unit)
WHERE rd.rule_key = 'PG-TRAN-002'
ON CONFLICT (rule_id, severity) DO NOTHING;


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
WHERE rule_key = 'PG-TRAN-002'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;
