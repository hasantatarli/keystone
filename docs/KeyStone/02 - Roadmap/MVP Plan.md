# PostgreSQL MVP Plan

**Status:** Current  
**Last Updated:** 2026-10-05

## Purpose

Order the work required to turn the current PostgreSQL implementation into something DataWiser can use in real engagements: one-off health checks for prospective customers and unattended continuous assessment for long-term DBA customers (see Product Strategy → Usage Scenarios).

This plan is product-oriented. Detailed working status lives in `docs/DEVELOPMENT_STATUS.md` in the repository.

## Where We Are (2026-10-05)

- Collection foundation: targets, assignments, queue, workers, run history, eleven PostgreSQL collectors including host and session activity evidence.
- Engineering Intelligence foundation: Dictionary tables, generic assessment engine with evidence and evaluator registries, freshness validation, findings with recommendations.
- Five rules across three assessments (PG_CONNECTION_HEALTH, PG_TRANSACTION_HEALTH, PG_REPLICATION_HEALTH), lab-verified and covered by automated tests.
- Everything is still operated by hand: collection is queued with SQL, the worker and the engine are started from the command line, and there is no report.

## Phases

### Phase 0 — Foundation hardening

- Bring the documentation vault up to date and create the Engineering Intelligence Rule Catalog.
- **Assessment Result model:** persist, for every rule in every run, whether the check was HEALTHY, ATTENTION_REQUIRED or INSUFFICIENT_EVIDENCE. This implements the outcome model already defined in the Health Assessment Playbook, Reference Architecture and ADR-0010; today a skipped rule is only printed to the console.
- **Failure visibility:** an assessment run that fails technically must end as FAILED instead of disappearing (Engineering Principle 5).

### Phase 1 — Manual Assessment

- **One-command health check:** run a set of assessments against a target and collect the required evidence first, through the existing execution engine. Replaces the manual queue / worker / engine sequence.
- **Report:** a readable health check report generated from a run: coverage, healthy areas, findings, insufficient evidence, recommendations.

Outcome: a usable one-off health check for a prospective customer.

### Phase 2 — Continuous Assessment

- **Scheduler:** turn `SCHEDULED` collector assignments into queued work at their interval; run assessments after relevant evidence arrives.
- **Finding lifecycle:** recognise that a condition is the same across runs (new, ongoing, escalated, resolved) instead of creating a new finding every run.
- **Finding-driven notification:** notify the engineer when findings appear, escalate, resolve or when evidence becomes insufficient (ADR-0013).

Outcome: Keystone can run unattended in a long-term customer engagement.

### Phase 3 — Patterns and outliers

- Baselines, trends and outlier detection over collected history. This is Keystone's main differentiator against one-off tools.

### Continuous track — rule coverage

Runs alongside every phase. New rules are derived from the MVP evidence matrix (Design History, 2026-09-21) and real engagements. The coverage of one-off tools such as `awslabs/pg-collector` is used as the minimum bar for the Manual Assessment report.

The threshold model limitation (one value per severity) is revisited when the first rule that genuinely needs multiple parameters is implemented, not before.

### After the MVP

- Web interface on top of the same service layer as the command line (ADR-0002: CLI and automation first).
- Real replication slot tests on lab VM snapshots.
- Resource-retaining aborted transaction rule candidate, migration checksum verification, advanced RCA, AI Engineering Assistant, commercial packaging.

## Readiness Criteria for a First Real Engagement

- One command performs a health check without hand-written SQL.
- The report is understandable without the founder present.
- Rule coverage is at least comparable to one-off tools for the covered areas.
- Keystone has been run side by side with a manual health check on at least one real system, and the differences have been reviewed.
- A short "what Keystone collects and does not do" document exists for customers (read-only access, no agent, collector SQL is visible).
