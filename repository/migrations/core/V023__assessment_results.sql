/*
===============================================================================
Migration No : 023
Version      : V023
Title        : Assessment Results

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds keystone.assessment_result (one outcome per evaluated rule and run),
the PARTIAL assessment run status and assessment_run.status_message.
Implements ADR-0014.
===============================================================================
*/


/*
Design notes (ADR-0014)
-----------------------
outcome:
  HEALTHY               rule evaluated, no finding
  ATTENTION_REQUIRED    rule evaluated, one or more findings
  INSUFFICIENT_EVIDENCE required evidence missing or stale, rule not evaluated
  ERROR                 technical failure while evaluating the rule

max_severity is stored once at evaluation time so reports and notifications do
not have to recompute it from findings. It is set only for ATTENTION_REQUIRED.

assessment_run.status keeps its technical meaning:
  RUNNING, SUCCESS, PARTIAL (at least one rule ended ERROR), FAILED (engine
  failure). It does not describe database health; assessment_result does.
===============================================================================
*/


/* ============================================================================
   ASSESSMENT RUN
   ============================================================================ */

ALTER TABLE keystone.assessment_run
    DROP CONSTRAINT ck_assessment_run_status;

ALTER TABLE keystone.assessment_run
    ADD CONSTRAINT ck_assessment_run_status
        CHECK (
            status IN ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED')
        );

ALTER TABLE keystone.assessment_run
    ADD COLUMN status_message TEXT;


/* ============================================================================
   ASSESSMENT RESULT
   ============================================================================ */

CREATE TABLE keystone.assessment_result
(
    assessment_result_id  BIGINT GENERATED ALWAYS AS IDENTITY,
    assessment_run_id     BIGINT       NOT NULL,
    rule_id               BIGINT       NOT NULL,

    outcome               VARCHAR(30)  NOT NULL,
    max_severity          VARCHAR(20),
    finding_count         INTEGER      NOT NULL DEFAULT 0,

    /*
    Human-readable explanation, for example the evidence age and the allowed
    age for INSUFFICIENT_EVIDENCE, or the error message for ERROR.
    */
    reason                TEXT,

    evaluated_at          TIMESTAMPTZ  NOT NULL,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT pk_assessment_result
        PRIMARY KEY (assessment_result_id),

    CONSTRAINT fk_assessment_result_run
        FOREIGN KEY (assessment_run_id)
        REFERENCES keystone.assessment_run (assessment_run_id),

    CONSTRAINT fk_assessment_result_rule
        FOREIGN KEY (rule_id)
        REFERENCES keystone.rule_definition (rule_id),

    CONSTRAINT uq_assessment_result_run_rule
        UNIQUE (assessment_run_id, rule_id),

    CONSTRAINT ck_assessment_result_outcome
        CHECK (
            outcome IN (
                'HEALTHY',
                'ATTENTION_REQUIRED',
                'INSUFFICIENT_EVIDENCE',
                'ERROR'
            )
        ),

    CONSTRAINT ck_assessment_result_max_severity
        CHECK (
            max_severity IS NULL
            OR max_severity IN ('INFO', 'WARNING', 'CRITICAL')
        ),

    CONSTRAINT ck_assessment_result_finding_count
        CHECK (finding_count >= 0),

    /*
    Keep outcome, severity and finding count consistent: only
    ATTENTION_REQUIRED has findings and a severity.
    */
    CONSTRAINT ck_assessment_result_consistency
        CHECK (
            (
                outcome = 'ATTENTION_REQUIRED'
                AND max_severity IS NOT NULL
                AND finding_count > 0
            )
            OR
            (
                outcome <> 'ATTENTION_REQUIRED'
                AND max_severity IS NULL
                AND finding_count = 0
            )
        )
);

CREATE INDEX ix_assessment_result_rule
    ON keystone.assessment_result (rule_id);
