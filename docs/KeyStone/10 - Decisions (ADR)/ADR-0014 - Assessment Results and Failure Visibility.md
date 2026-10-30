# ADR-0014 — Assessment Results and Failure Visibility

**Status:** Approved  
**Date:** 2026-10-14  
**Implements:** ADR-0010 (assessment outcomes), Engineering Principle 5 (Preserve Failure Visibility)

## Context

The architecture already requires every check to end as healthy, attention required or insufficient evidence, and states that zero findings must never be read as proof of health. The implementation did not persist this: a rule skipped for missing or stale evidence was only printed to the console, and the assessment run still ended SUCCESS.

Failures were also invisible. The assessment engine had no exception handling and did not commit explicitly, so an error rolled back the whole run and left no trace (a missing run number in the lab sequence is the likely symptom). Outside collector and migration history, the application had no logging at all; technical errors existed only in a console window. This is not acceptable once Keystone runs unattended (Product Strategy → Usage Scenarios).

## Decision

### Assessment results

Every assessment run records one **assessment result per evaluated rule** in `keystone.assessment_result`, with:

- `outcome`:
  - `HEALTHY` — the rule was evaluated and produced no finding,
  - `ATTENTION_REQUIRED` — the rule produced one or more findings,
  - `INSUFFICIENT_EVIDENCE` — required evidence was missing or stale; the rule was not evaluated,
  - `ERROR` — the rule could not be evaluated because of a technical failure;
- `max_severity` — the highest severity among the rule's findings, stored once at evaluation time (NULL unless `ATTENTION_REQUIRED`). Reports and future notifications read it directly instead of recomputing it from findings;
- `finding_count`, a human-readable `reason` (for example the evidence age and allowed age, or the error message), and the evaluation time.

`assessment_run.status` keeps its technical meaning and does not describe database health.

### Rule-level failure isolation

A failure inside one rule (evaluator or evidence loading) is recorded as that rule's `ERROR` result and does not stop the other rules. A run in which at least one rule ended `ERROR` finishes with the run status `PARTIAL`. A failure of the engine itself (for example losing the repository connection) ends the run as `FAILED`. In every case the run and its results remain persisted.

### Logging

Two layers with different purposes:

- **Business events stay in the repository** as product data: collector run history, migration history, assessment runs, assessment results, findings.
- **Technical logging** uses Python's standard `logging` with one shared configuration:
  - **file** (rotating), always, for all technical log records. It works even when the repository is unreachable;
  - **repository table `keystone.event_log`** for significant events only (WARNING and above, component start/stop), so they can be queried and later shown in the user interface.

Repository logging uses a **separate autocommit connection**, so an event is not rolled back with the failed work it describes. If the repository cannot be written, the record still reaches the file and the application continues.

### Rollout

- Phase 0: assessment results, rule-level isolation, shared logging configuration, assessment engine logging.
- Phase 2 (with the scheduler): worker logging, replacing console output in the component that runs unattended.

## Consequences

- Reports can show healthy areas, problems and areas that could not be assessed, with reasons.
- One faulty rule cannot hide the results of the others, and its failure stays visible.
- Lost runs are no longer possible; every run ends RUNNING → SUCCESS, PARTIAL or FAILED with its results.
- Errors that happen while nobody is watching remain available afterwards, including repository outages.
- `event_log` needs a retention policy once continuous operation produces volume; deferred until then.

## Addendum (2026-10-30, Hasan)

An INSUFFICIENT_EVIDENCE result stays an outcome, never a finding: a finding says a problem was found, an unassessed check says nothing could be seen, and a severity for the unknown would be invented. Reports draw attention to it instead: the executive part has a "Checks not assessed" card that groups the checks by cause (a failed collection or missing source is listed once with every check it stopped) and says what to do, and the verdict states how many checks could not be done. An area with a check not assessed is "partly assessed", never "no problems".
