/*
===============================================================================
Migration No : 016
Version      : V016
Title        : Engineering Intelligence Foundation

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Creates the initial Engineering Intelligence data model.

The model separates reusable engineering knowledge (Dictionary) from
assessment execution results.

Dictionary:
- assessment_definition
- rule_definition
- rule_threshold

Execution / Results:
- assessment_run
- finding
===============================================================================
*/


/* ============================================================================
   ASSESSMENT DEFINITION
   ============================================================================ */

CREATE TABLE keystone.assessment_definition
(
    assessment_id      BIGINT GENERATED ALWAYS AS IDENTITY,
    assessment_key     VARCHAR(100) NOT NULL,
    name               VARCHAR(200) NOT NULL,
    provider           VARCHAR(50)  NOT NULL,
    description        TEXT,
    is_enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT pk_assessment_definition
        PRIMARY KEY (assessment_id),

    CONSTRAINT uq_assessment_definition_key
        UNIQUE (assessment_key)
);


/* ============================================================================
   RULE DEFINITION
   ============================================================================ */

CREATE TABLE keystone.rule_definition
(
    rule_id             BIGINT GENERATED ALWAYS AS IDENTITY,
    assessment_id       BIGINT       NOT NULL,

    rule_key             VARCHAR(100) NOT NULL,
    name                 VARCHAR(200) NOT NULL,
    description          TEXT,

    evidence_source      VARCHAR(100) NOT NULL,

    /*
    Used by rules whose severity does not depend on thresholds.
    Threshold-based rules may leave this NULL.
    */
    default_severity     VARCHAR(20),

    finding_template     TEXT         NOT NULL,
    recommendation      TEXT         NOT NULL,

    is_enabled           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT pk_rule_definition
        PRIMARY KEY (rule_id),

    CONSTRAINT fk_rule_definition_assessment
        FOREIGN KEY (assessment_id)
        REFERENCES keystone.assessment_definition (assessment_id),

    CONSTRAINT uq_rule_definition_key
        UNIQUE (rule_key),

    CONSTRAINT ck_rule_definition_default_severity
        CHECK (
            default_severity IS NULL
            OR default_severity IN ('INFO', 'WARNING', 'CRITICAL')
        )
);


/* ============================================================================
   RULE THRESHOLD
   ============================================================================ */

CREATE TABLE keystone.rule_threshold
(
    threshold_id        BIGINT GENERATED ALWAYS AS IDENTITY,
    rule_id             BIGINT         NOT NULL,

    severity            VARCHAR(20)    NOT NULL,
    threshold_value     NUMERIC(20,4)  NOT NULL,
    threshold_unit      VARCHAR(30)    NOT NULL,

    CONSTRAINT pk_rule_threshold
        PRIMARY KEY (threshold_id),

    CONSTRAINT fk_rule_threshold_rule
        FOREIGN KEY (rule_id)
        REFERENCES keystone.rule_definition (rule_id),

    CONSTRAINT ck_rule_threshold_severity
        CHECK (
            severity IN ('INFO', 'WARNING', 'CRITICAL')
        ),

    CONSTRAINT ck_rule_threshold_value
        CHECK (
            threshold_value >= 0
        ),

    CONSTRAINT uq_rule_threshold_rule_severity
        UNIQUE (rule_id, severity)
);


/* ============================================================================
   ASSESSMENT RUN
   ============================================================================ */

CREATE TABLE keystone.assessment_run
(
    assessment_run_id   BIGINT GENERATED ALWAYS AS IDENTITY,
    assessment_id       BIGINT       NOT NULL,
    target_id           BIGINT       NOT NULL,

    started_at          TIMESTAMPTZ  NOT NULL,
    finished_at         TIMESTAMPTZ,

    status              VARCHAR(20)  NOT NULL,

    CONSTRAINT pk_assessment_run
        PRIMARY KEY (assessment_run_id),

    CONSTRAINT fk_assessment_run_assessment
        FOREIGN KEY (assessment_id)
        REFERENCES keystone.assessment_definition (assessment_id),

    CONSTRAINT fk_assessment_run_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target (target_id),

    CONSTRAINT ck_assessment_run_status
        CHECK (
            status IN ('RUNNING', 'SUCCESS', 'FAILED')
        ),

    CONSTRAINT ck_assessment_run_time
        CHECK (
            finished_at IS NULL
            OR finished_at >= started_at
        )
);

CREATE INDEX ix_assessment_run_target_started
    ON keystone.assessment_run
    (
        target_id,
        started_at DESC
    );


/* ============================================================================
   FINDING
   ============================================================================ */

CREATE TABLE keystone.finding
(
    finding_id          BIGINT GENERATED ALWAYS AS IDENTITY,
    assessment_run_id   BIGINT       NOT NULL,
    rule_id             BIGINT       NOT NULL,

    severity            VARCHAR(20)  NOT NULL,

    title               VARCHAR(300) NOT NULL,
    finding_text        TEXT         NOT NULL,
    recommendation      TEXT         NOT NULL,

    /*
    Actual measured value which caused the rule to trigger.
    Not every rule is numeric, therefore this is nullable.
    */
    observed_value      NUMERIC(20,4),
    observed_unit       VARCHAR(30),

    /*
    Optional reference to the specific subject within the target.
    Examples:
      PID 19066
      database postgres
      table public.orders

    Kept generic for MVP. A richer evidence/subject model can be
    introduced later if justified.
    */
    subject_type        VARCHAR(50),
    subject_identifier  VARCHAR(300),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT pk_finding
        PRIMARY KEY (finding_id),

    CONSTRAINT fk_finding_assessment_run
        FOREIGN KEY (assessment_run_id)
        REFERENCES keystone.assessment_run (assessment_run_id),

    CONSTRAINT fk_finding_rule
        FOREIGN KEY (rule_id)
        REFERENCES keystone.rule_definition (rule_id),

    CONSTRAINT ck_finding_severity
        CHECK (
            severity IN ('INFO', 'WARNING', 'CRITICAL')
        )
);

CREATE INDEX ix_finding_assessment_run
    ON keystone.finding (assessment_run_id);

CREATE INDEX ix_finding_rule
    ON keystone.finding (rule_id);