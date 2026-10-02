/*
===============================================================================
Migration No : 020
Version      : V020
Title        : Add Aborted Idle Transaction Connection Rule

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds the PostgreSQL Connection Health assessment and a rule that detects
client connections left idle in an aborted transaction state.

The rule uses PG_CONNECTION_ACTIVITY system-level evidence and produces a
WARNING finding when the configured connection-count threshold is reached.
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
    'PG_CONNECTION_HEALTH',
    'Connection Health',
    'PostgreSQL',
    'Evaluates PostgreSQL connection activity for unhealthy session states and connection-related operational risks.'
);


/* ============================================================================
   PG-CONN-001 - ABORTED IDLE TRANSACTION CONNECTIONS
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
    'PG-CONN-001',
    'Aborted Idle Transaction Connections',
    'Detects client connections left idle in an aborted transaction state.',
    'PG_CONNECTION_ACTIVITY',
    NULL,
    '{connection_count} client connection(s) are idle in an aborted transaction state.',
    'Review the affected application transaction lifecycle and connection handling. Ensure failed transactions are rolled back and connections are returned to a clean state or closed.'
FROM keystone.assessment_definition
WHERE assessment_key = 'PG_CONNECTION_HEALTH';


/* ============================================================================
   RULE THRESHOLD
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
    1,
    'CONNECTION'
FROM keystone.rule_definition
WHERE rule_key = 'PG-CONN-001';


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
    'PG_CONNECTION_ACTIVITY',
    TRUE,
    600
FROM keystone.rule_definition
WHERE rule_key = 'PG-CONN-001';
