# PostgreSQL Health Assessment Playbook

**Status:** Draft  
**Last Updated:** 2026-09-19

## Purpose

Provide a standardized PostgreSQL engineering assessment using the same Keystone evidence, assessment, finding, RCA, and recommendation model used by Continuous Engineering.

Health Assessment is an **Assessment Profile**, not a separate analysis engine.

## Operating Modes

The Health Assessment profile may be executed in different evidence-acquisition modes:

- **Snapshot Assessment** — point-in-time and database-maintained cumulative evidence for a one-off Health Check.
- **Temporary Observation** — a bounded collection window, such as 24 hours or seven days, when trends or workload behavior materially improve the assessment.
- **Continuous Engineering** — recurring collection and continuously updated assessments using historical evidence.

The selected mode affects evidence coverage and therefore the conclusions Keystone can support.

## Assessment Outcomes

Each engineering check should explicitly produce one of these outcomes:

- **HEALTHY** — required evidence was assessed and no attention-requiring condition was detected.
- **ATTENTION_REQUIRED** — the assessment produced one or more Findings.
- **NOT_ASSESSED / INSUFFICIENT_EVIDENCE** — the required evidence is unavailable or insufficient.

Zero Findings must not be interpreted as complete health when assessment coverage is incomplete.

## Engineering Flow

**Evidence → Derived Evidence → Assessment → Finding → RCA → Recommendation**

Findings represent conditions requiring attention. Healthy checks remain Assessment Results rather than artificial positive Findings.

Where a Finding is detected, Keystone should perform RCA to the extent supported by available evidence. RCA may include:

- predefined hypotheses,
- supporting evidence,
- contradicting evidence,
- missing evidence,
- evidence-grounded confidence,
- alternative hypotheses.

A one-off Health Assessment does not guarantee complete root-cause identification. The report must distinguish a supported RCA from an evidence gap rather than overstate certainty.

## Evidence Coverage

The Health Assessment profile defines the evidence required for its engineering checks.

For each assessment area Keystone should be able to show:

- what was assessed,
- what evidence was available,
- what could not be assessed,
- which missing evidence limits Finding detection or RCA,
- whether a longer observation window would materially improve the result.

This makes assessment coverage visible and allows Snapshot Assessment to remain useful without pretending to have historical evidence that was never collected.

## Assessment Areas

The detailed PostgreSQL V1 Assessment Catalogue will define the final checks. Candidate domains include:

- instance and topology,
- architecture and configuration,
- database and storage capacity,
- sessions and connections,
- transactions and wraparound,
- maintenance / vacuum / analyze,
- locking and concurrency,
- table and index health,
- replication and high availability,
- backup and recovery,
- security,
- reliability and errors,
- workload and performance indicators,
- historical change and trend analysis where evidence exists.

## Keystone Dictionary

Assessment definitions, Finding definitions, RCA models, evidence requirements, standard hypotheses, and Recommendation definitions are maintained as Keystone engineering knowledge.

PostgreSQL-specific concepts remain provider-specific. Generic engineering concepts may be shared across providers where the underlying meaning is genuinely common.

## Deliverables

A Health Assessment may produce:

- Executive Summary
- Assessment Coverage
- Environment / Architecture Summary
- Healthy Assessment Areas
- Findings and Risk Summary
- Root Cause Analysis where evidence permits
- Missing Evidence / Assessment Limitations
- Recommendations
- Engineering Roadmap
- Supporting Evidence and History where applicable

## Report Structure

The final report structure will be derived from the V1 Assessment Catalogue and Presentation model rather than designed independently from them.
