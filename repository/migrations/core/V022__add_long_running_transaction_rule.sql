/*
===============================================================================
Migration No : 022
Version      : V022
Title        : Add Long-Running Transaction Rule

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PG-TRAN-003, which detects client transactions that have been open for a
long time regardless of session state, using PG_ACTIVITY_SNAPSHOT evidence.
===============================================================================
*/


/*
Why this rule exists
--------------------
PG-TRAN-001 measures how long a session has been idle inside a transaction.
A transaction can also hold the xmin horizon and its locks for a long time
while it keeps working, or after long work followed by a short idle period.
PG-TRAN-003 measures transaction age (captured_at - transaction_start) for
every state except 'idle in transaction (aborted)', whose top-level failure
has already released the snapshot and is covered by PG-CONN-001.

A session idle in a transaction for a long time can match PG-TRAN-001 and
PG-TRAN-003 at the same time. This is intentional: they answer different
engineering questions (forgotten transaction vs. held xmin horizon).

Inserts are idempotent so the migration is safe on repositories where the
rule might already exist.
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
    'PG-TRAN-003',
    'Long-Running Transaction',
    'Detects client transactions that have been open beyond the configured thresholds, regardless of whether the session is active or idle.',
    'PG_ACTIVITY_SNAPSHOT',
    NULL,
    'Session {pid} has had a transaction open for {duration_seconds} seconds (current state: {state}).',
    'Identify the workload behind the transaction. Long-running transactions hold the xmin horizon and their locks, which prevents VACUUM from removing dead tuples and can cause bloat and lock waits. Consider splitting batch work into smaller transactions and review application transaction boundaries.'
FROM keystone.assessment_definition
WHERE assessment_key = 'PG_TRANSACTION_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;


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
    rd.rule_id,
    t.severity,
    t.threshold_value,
    t.threshold_unit
FROM keystone.rule_definition AS rd
CROSS JOIN
(
    VALUES
        ('WARNING',  1800, 'SECOND'),
        ('CRITICAL', 3600, 'SECOND')
) AS t (severity, threshold_value, threshold_unit)
WHERE rd.rule_key = 'PG-TRAN-003'
ON CONFLICT (rule_id, severity) DO NOTHING;


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
    'PG_ACTIVITY_SNAPSHOT',
    TRUE,
    600
FROM keystone.rule_definition
WHERE rule_key = 'PG-TRAN-003'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;
