/*
===============================================================================
Migration No : 028
Version      : V028
Title        : Health Check

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds keystone.health_check (one manual health check of a target), the
collections it requested (keystone.health_check_collection) and
assessment_run.health_check_id. Implements the one-command health check of
MVP Plan Phase 1.
===============================================================================
*/


/*
Design notes (ADR-0015, ADR-0009)
---------------------------------
A health check is the manual assessment pipeline run once: queue the
collectors the assessments need (plus report context collectors), run them,
then run the assessments. It uses the normal queue, worker and run history;
nothing is collected in a second way.

A health check of a SYSTEM target also covers its NODE targets: NODE-scope
collectors run on every node.

health_check_collection keeps one row per requested collection, including
those that could not be queued (no assignment and no suitable connection),
so the report can say what was not collected and why. task_id links to
collector_run_history.task_id for the outcome.
===============================================================================
*/


/* ============================================================================
   HEALTH CHECK
   ============================================================================ */

CREATE TABLE keystone.health_check
(
    health_check_id   BIGINT GENERATED ALWAYS AS IDENTITY,

    target_id         BIGINT       NOT NULL,

    started_at        TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
    finished_at       TIMESTAMPTZ,

    status            VARCHAR(20)  NOT NULL,
    status_message    TEXT,

    requested_by      VARCHAR(150),

    CONSTRAINT pk_health_check
        PRIMARY KEY (health_check_id),

    CONSTRAINT fk_health_check_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target (target_id),

    CONSTRAINT ck_health_check_status
        CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED'))
);

CREATE INDEX ix_health_check_target_started
    ON keystone.health_check (target_id, started_at DESC);

COMMENT ON TABLE keystone.health_check IS
'One manual health check of a target: collect required evidence once, then assess.';

COMMENT ON COLUMN keystone.health_check.status IS
'RUNNING, COMPLETED (assessments ran; individual collections may have failed) or FAILED (the health check itself failed).';


/* ============================================================================
   HEALTH CHECK COLLECTION
   ============================================================================ */

CREATE TABLE keystone.health_check_collection
(
    health_check_collection_id  BIGINT GENERATED ALWAYS AS IDENTITY,

    health_check_id   BIGINT       NOT NULL,
    target_id         BIGINT       NOT NULL,
    collector_key     VARCHAR(100) NOT NULL,

    /*
    EVIDENCE: required by a rule of the selected assessments.
    CONTEXT:  describes the target in the report (versions, databases).
    */
    purpose           VARCHAR(20)  NOT NULL,

    assignment_id     BIGINT,
    task_id           BIGINT,

    /*
    QUEUED, then the run history status (SUCCESS, PARTIAL_SUCCESS, FAILED,
    CONNECTION_FAILED, TIMEOUT, STALE), or:
    NOT_COLLECTED     no assignment and no suitable connection
    WAIT_LIMIT        still running when the per-collector wait limit passed
    */
    status            VARCHAR(30)  NOT NULL,
    status_message    TEXT,

    CONSTRAINT pk_health_check_collection
        PRIMARY KEY (health_check_collection_id),

    CONSTRAINT fk_health_check_collection_check
        FOREIGN KEY (health_check_id)
        REFERENCES keystone.health_check (health_check_id),

    CONSTRAINT fk_health_check_collection_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target (target_id),

    CONSTRAINT ck_health_check_collection_purpose
        CHECK (purpose IN ('EVIDENCE', 'CONTEXT'))
);

CREATE INDEX ix_health_check_collection_check
    ON keystone.health_check_collection (health_check_id);

COMMENT ON TABLE keystone.health_check_collection IS
'Collections requested by a health check, including those that could not be queued.';


/* ============================================================================
   ASSESSMENT RUN
   ============================================================================ */

ALTER TABLE keystone.assessment_run
    ADD COLUMN health_check_id BIGINT;

ALTER TABLE keystone.assessment_run
    ADD CONSTRAINT fk_assessment_run_health_check
        FOREIGN KEY (health_check_id)
        REFERENCES keystone.health_check (health_check_id);

CREATE INDEX ix_assessment_run_health_check
    ON keystone.assessment_run (health_check_id)
    WHERE health_check_id IS NOT NULL;

COMMENT ON COLUMN keystone.assessment_run.health_check_id IS
'Health check that started this run; NULL for scheduled and other manual runs.';
