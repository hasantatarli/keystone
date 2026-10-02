# Keystone Development Status

Last updated: 2026-10-02

This document is the working checkpoint for the PostgreSQL MVP. It records what is implemented and verified, what is currently being worked on, and what comes next. It is intentionally narrower than a long-term product roadmap.

## MVP Goal

Keystone connects to a PostgreSQL system, automatically collects evidence, applies deterministic and explainable engineering intelligence, and produces an evidence-backed health assessment with actionable findings and recommendations.

Current conceptual flow:

`Target -> Collector -> Evidence -> Intelligence Evaluation -> Assessment -> Finding -> Recommendation`

AI is not the core intelligence layer. The PostgreSQL MVP first establishes deterministic, testable DBA engineering rules.

## Current Architecture Baseline

- PostgreSQL 15+ is the MVP database target.
- The central Keystone repository is PostgreSQL.
- Provider-independent metadata and execution state live in the `keystone` schema.
- PostgreSQL-specific evidence lives in the `postgresql` schema.
- Collector execution already provides the automation foundation: Target -> Collector -> Execution -> Evidence Repository.
- Rule evaluation remains Python. A generic rule DSL is intentionally out of scope until real rules justify one.
- Severity values are INFO, WARNING, and CRITICAL.
- Collection frequency and evidence freshness are separate concepts.
- Missing or stale required evidence must not silently mean healthy.

## Engineering Intelligence Implemented

Five real PostgreSQL rules are currently implemented.

| Rule | Assessment | Evidence | Result logic |
| --- | --- | --- | --- |
| PG-TRAN-001 | PG_TRANSACTION_HEALTH | PG_ACTIVITY_SNAPSHOT | Long idle transaction; WARNING/CRITICAL by duration threshold |
| PG-TRAN-002 | PG_TRANSACTION_HEALTH | PG_TRANSACTION_WRAPAROUND | Database XID age; WARNING/CRITICAL by transaction threshold |
| PG-REP-001 | PG_REPLICATION_HEALTH | PG_REPLICATION_SLOTS | WAL status `extended`; default WARNING |
| PG-REP-002 | PG_REPLICATION_HEALTH | PG_REPLICATION_SLOTS | WAL status `unreserved` or `lost`; default CRITICAL |
| PG-CONN-001 | PG_CONNECTION_HEALTH | PG_CONNECTION_ACTIVITY | Aborted idle transaction connection count; WARNING from 1 connection |

The Dictionary currently contains assessment definitions, rule definitions, thresholds, and evidence requirements. Runtime results are persisted as assessment runs and findings.

## Latest Engine Refactor

The assessment engine has moved away from a growing rule-specific `if/elif` orchestration model.

The intended model is:

- `EVIDENCE_LOADERS` maps an evidence source to the repository loader that retrieves it.
- `RULE_EVALUATORS` maps a rule key to its Python evaluator.
- Evaluators use a common `(rows, rule, thresholds) -> findings` contract.
- `run_assessment()` loads enabled rules from the Dictionary and resolves their evidence/evaluator through the registries.
- Evidence is loaded on demand from the rule's evidence requirements rather than eagerly loading every evidence type for every assessment.
- Evidence is cached per source during an assessment run so multiple rules can reuse it.
- Rule-specific DBA logic remains in Python evaluators.

This keeps configuration data-driven while keeping engineering logic code-driven. We are deliberately not introducing a generic rule expression language.

### Verification status

The refactored engine has been executed successfully through the registry-driven path for `PG_CONNECTION_HEALTH`.

The latest observed run reached PG-CONN-001, resolved its `PG_CONNECTION_ACTIVITY` requirement, performed the freshness check, and correctly skipped evaluation because the available evidence was older than the configured 600-second maximum age.

This verifies the registry lookup, requirement-driven evidence loading, and freshness path. A fresh PG_CONNECTION_ACTIVITY collection is the next regression step so the evaluator itself can be exercised again after the refactor.

## Known Issues / Open Design Decisions

### 1. Assessment run failure handling

An exception during evaluation can currently leave an `assessment_run` in RUNNING state. This was observed during refactor testing. The engine needs explicit exception handling so technical execution failures finish the run as FAILED before the exception is propagated or reported.

### 2. Assessment outcome vs technical status

A rule can be skipped because required evidence is missing or stale while the assessment run still finishes with status SUCCESS.

SUCCESS currently means technical execution success; it must not be interpreted as a healthy database. We need an explicit MVP decision for representing insufficient evidence without overloading technical run status.

### 3. Threshold model

The current `rule_threshold` model supports one threshold value per rule/severity. This works for the first five rules but will become limiting for rules that require multiple metrics, such as a vacuum rule combining dead tuple count and ratio.

Do not introduce a generic DSL. Revisit the smallest useful extension, such as named metrics or rule parameters, when implementing the next rule that genuinely needs it.

### 4. Multi-source evaluators

The orchestration can resolve evidence requirements generically, but the current evaluator contract intentionally supports one evidence row-set per rule. Do not generalize this until a real rule requires multiple evidence sources.

## Active Work

Current checkpoint: stabilize and regression-test the five-rule Engineering Intelligence engine.

Immediate work sequence:

1. Produce fresh PG_CONNECTION_ACTIVITY evidence and re-run PG_CONNECTION_HEALTH.
2. Regression-test PG_TRANSACTION_HEALTH after the registry refactor.
3. Regression-test PG_REPLICATION_HEALTH after the registry refactor.
4. Add automated regression coverage for registry completeness and the common evaluator contract.
5. Fix assessment-run exception handling so failed executions do not remain RUNNING.
6. Decide the MVP representation for missing/stale required evidence.
7. Revisit the threshold model only when the next real rule requires multiple parameters.

Do not add a sixth rule before the current five-rule checkpoint is stable.

## Next Documentation Checkpoint

With five real rules now implemented, a human-readable Engineering Intelligence Rule Catalog is justified. It should document each rule's purpose, evidence source, freshness requirement, evaluation criteria, metric/thresholds, subject, expected finding, and recommendation.

The catalog should explain engineering intent without duplicating machine-readable Dictionary metadata unnecessarily.

## Explicitly Deferred / V1 Sonrasi

The following are intentionally outside the current PostgreSQL MVP implementation focus:

- Generic rule DSL / expression language
- Full provider-independent intelligence abstraction
- Advanced RCA engine
- Confidence scoring
- Continuous Engineering / 24x7 intelligence architecture
- Notification and alert policy engine
- Automated corrective actions
- AI agents as the core decision engine
- Full UI implementation before the backend intelligence path is stable

## Development Workflow

For architecture-sensitive changes:

`Discuss -> decide -> implement -> static/automated checks -> review diff -> lab/E2E test -> verify -> continue`

Implementation can be performed by the AI development partner after the design is agreed, but generated code is not considered complete merely because it was pushed. It must pass the available static/automated checks and then the relevant Keystone lab/E2E verification.

Code should include concise comments/docstrings where they explain architectural intent, contracts, non-obvious behavior, or why a design choice exists. Avoid comments that merely restate obvious syntax.
