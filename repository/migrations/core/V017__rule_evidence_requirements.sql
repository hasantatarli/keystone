/*
===============================================================================
Migration No : 017
Version      : V017
Title        : Add Rule Evidence Requirements

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds evidence requirements for intelligence rules.

A rule may depend on one or more evidence sources. Each evidence requirement
defines whether the evidence is required and how fresh the evidence must be
when the rule is evaluated.

Collection frequency and evidence freshness are intentionally separate
concepts.
===============================================================================
*/

CREATE TABLE keystone.rule_evidence_requirement
(
    requirement_id BIGINT GENERATED ALWAYS AS IDENTITY,
    rule_id BIGINT NOT NULL,
    evidence_source VARCHAR(100) NOT NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    max_age_seconds INTEGER,

    CONSTRAINT pk_rule_evidence_requirement
        PRIMARY KEY (requirement_id),

    CONSTRAINT fk_rule_evidence_requirement_rule
        FOREIGN KEY (rule_id)
        REFERENCES keystone.rule_definition (rule_id),

    CONSTRAINT uq_rule_evidence_requirement
        UNIQUE (rule_id, evidence_source),

    CONSTRAINT ck_rule_evidence_requirement_max_age
        CHECK
        (
            max_age_seconds IS NULL
            OR max_age_seconds > 0
        )
);


CREATE INDEX ix_rule_evidence_requirement_rule
    ON keystone.rule_evidence_requirement (rule_id);


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
WHERE rule_key = 'PG-TRAN-001';