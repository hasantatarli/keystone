/*
===============================================================================
Migration No : 026
Version      : V026
Title        : Assessment Schedule

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds per-target assessment schedules with Dictionary defaults, a function that
copies the defaults to a target, assessment_run.scheduled_at, and the view
keystone.schedule_consistency_warning. Implements ADR-0015.
===============================================================================
*/


/*
Design notes (ADR-0015)
-----------------------
Assessments run on the same clock-aligned grid as collectors, shifted by
offset_seconds (default 30) so that evidence collected at the start of the
slot is already stored when the assessment evaluates it.

Defaults live in the Dictionary (assessment_definition.default_interval_seconds)
and are copied to a target by keystone.apply_default_assessment_schedules();
after that the target's rows are edited, not the defaults.

schedule_consistency_warning lists configurations under which a rule cannot be
evaluated in continuous mode: a required collector is not scheduled for the
target, or its interval is longer than the rule's freshness limit. It does
not describe database health; assessment_result does.
===============================================================================
*/


/* ============================================================================
   DEFAULT INTERVALS
   ============================================================================ */

ALTER TABLE keystone.assessment_definition
    ADD COLUMN default_interval_seconds INTEGER;

ALTER TABLE keystone.assessment_definition
    ADD CONSTRAINT ck_assessment_definition_default_interval
        CHECK (default_interval_seconds IS NULL OR default_interval_seconds > 0);

COMMENT ON COLUMN keystone.assessment_definition.default_interval_seconds IS
'Interval copied to new assessment schedules; NULL means the assessment is not scheduled by default.';

UPDATE keystone.assessment_definition
SET default_interval_seconds = 300
WHERE assessment_key IN
(
    'PG_CONNECTION_HEALTH',
    'PG_REPLICATION_HEALTH',
    'PG_TRANSACTION_HEALTH'
)
  AND default_interval_seconds IS NULL;


/* ============================================================================
   ASSESSMENT SCHEDULE
   ============================================================================ */

CREATE TABLE keystone.assessment_schedule
(
    schedule_id       BIGINT GENERATED ALWAYS AS IDENTITY,

    assessment_id     BIGINT      NOT NULL,
    target_id         BIGINT      NOT NULL,

    interval_seconds  INTEGER     NOT NULL,
    offset_seconds    INTEGER     NOT NULL DEFAULT 30,
    is_enabled        BOOLEAN     NOT NULL DEFAULT TRUE,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT pk_assessment_schedule
        PRIMARY KEY (schedule_id),

    CONSTRAINT fk_assessment_schedule_assessment
        FOREIGN KEY (assessment_id)
        REFERENCES keystone.assessment_definition (assessment_id),

    CONSTRAINT fk_assessment_schedule_target
        FOREIGN KEY (target_id)
        REFERENCES keystone.target (target_id),

    CONSTRAINT uq_assessment_schedule
        UNIQUE (assessment_id, target_id),

    CONSTRAINT ck_assessment_schedule_interval
        CHECK (interval_seconds > 0),

    CONSTRAINT ck_assessment_schedule_offset
        CHECK (offset_seconds >= 0 AND offset_seconds < interval_seconds)
);

CREATE INDEX ix_assessment_schedule_target
    ON keystone.assessment_schedule (target_id);

COMMENT ON TABLE keystone.assessment_schedule IS
'Per-target schedule of an assessment, run by the Keystone Agent.';

COMMENT ON COLUMN keystone.assessment_schedule.offset_seconds IS
'Seconds after each grid slot at which the assessment runs (after collectors of the same slot).';


/* ============================================================================
   ASSESSMENT RUN
   ============================================================================ */

ALTER TABLE keystone.assessment_run
    ADD COLUMN scheduled_at TIMESTAMPTZ;

COMMENT ON COLUMN keystone.assessment_run.scheduled_at IS
'Planned start of a scheduled run; NULL for manual runs.';

CREATE INDEX ix_assessment_run_assessment_target_started
    ON keystone.assessment_run (assessment_id, target_id, started_at DESC);


/* ============================================================================
   COPY DEFAULTS TO A TARGET
   ============================================================================ */

CREATE FUNCTION keystone.apply_default_assessment_schedules(p_target_id BIGINT)
RETURNS INTEGER
LANGUAGE sql
AS $$
    WITH inserted AS
    (
        INSERT INTO keystone.assessment_schedule
            (assessment_id, target_id, interval_seconds)
        SELECT ad.assessment_id, t.target_id, ad.default_interval_seconds
        FROM keystone.target t
        JOIN keystone.assessment_definition ad
            ON ad.provider = t.provider
        WHERE t.target_id = p_target_id
          AND ad.is_enabled
          AND ad.default_interval_seconds IS NOT NULL
        ON CONFLICT (assessment_id, target_id) DO NOTHING
        RETURNING 1
    )
    SELECT count(*)::INTEGER FROM inserted;
$$;

COMMENT ON FUNCTION keystone.apply_default_assessment_schedules(BIGINT) IS
'Creates missing assessment schedules for a target from Dictionary defaults; returns the number created. Existing schedules are not changed.';


/* ============================================================================
   CONSISTENCY WARNINGS
   ============================================================================ */

CREATE VIEW keystone.schedule_consistency_warning AS
SELECT
    s.target_id,
    t.name                AS target_name,
    ad.assessment_key,
    rd.rule_key,
    rer.evidence_source,
    CASE
        WHEN ca.assignment_id IS NULL THEN 'NOT_SCHEDULED'
        ELSE 'INTERVAL_TOO_LONG'
    END                   AS problem,
    ca.interval_seconds   AS collector_interval_seconds,
    rer.max_age_seconds,
    CASE
        WHEN ca.assignment_id IS NULL THEN
            format('Collector %s is not scheduled for this target; the rule will end INSUFFICIENT_EVIDENCE.',
                   rer.evidence_source)
        ELSE
            format('Collector %s runs every %s s but the rule needs evidence not older than %s s.',
                   rer.evidence_source, ca.interval_seconds, rer.max_age_seconds)
    END                   AS detail
FROM keystone.assessment_schedule s
JOIN keystone.target t
    ON t.target_id = s.target_id
JOIN keystone.assessment_definition ad
    ON ad.assessment_id = s.assessment_id
JOIN keystone.rule_definition rd
    ON rd.assessment_id = ad.assessment_id
JOIN keystone.rule_evidence_requirement rer
    ON rer.rule_id = rd.rule_id
LEFT JOIN LATERAL
(
    SELECT ca.assignment_id, ca.interval_seconds
    FROM keystone.collector_assignment ca
    JOIN keystone.collector_definition cd
        ON cd.collector_id = ca.collector_id
    WHERE ca.target_id = s.target_id
      AND cd.collector_key = rer.evidence_source
      AND ca.execution_mode = 'SCHEDULED'
      AND ca.is_enabled
      AND cd.is_active
    ORDER BY ca.interval_seconds
    LIMIT 1
) ca ON TRUE
WHERE s.is_enabled
  AND t.is_active
  AND ad.is_enabled
  AND rd.is_enabled
  AND rer.is_required
  AND
  (
      ca.assignment_id IS NULL
      OR (rer.max_age_seconds IS NOT NULL AND ca.interval_seconds > rer.max_age_seconds)
  );

COMMENT ON VIEW keystone.schedule_consistency_warning IS
'Scheduled assessments whose rules cannot get fresh evidence: required collector not scheduled, or scheduled less often than the freshness limit.';
