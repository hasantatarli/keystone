# Keystone Development Status

Last updated: 2026-10-05

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

## Clean Install Integrity (2026-10-05)

### Finding

`PG_TRANSACTION_HEALTH` and `PG-TRAN-001` (with its 300/900 second thresholds) were inserted manually into the development repository on 2026-09-22, after V016, and were never added to a migration. V017 (PG-TRAN-001 evidence requirement) and V018 (PG-TRAN-002) depend on those rows.

On a clean install, V017 and V018 therefore inserted zero rows while still recording SUCCESS. The result was a Dictionary with 3 of the 5 rules and no Transaction Health assessment, without any error or warning. The development repository kept working because it carried the manual rows.

### Fix

- `V021__seed_transaction_health_assessment.sql` idempotently creates the Transaction Health assessment, PG-TRAN-001 and PG-TRAN-002 with their thresholds and evidence requirements. On an existing repository every insert is a no-op; existing rows are never updated. V016-V018 are not edited because applied migrations are immutable.
- `tests/test_intelligence_dictionary.py` adds:
  - clean-install contract tests: install into a disposable PostgreSQL database and assert the expected assessments, rules, thresholds and evidence requirements (`EXPECTED_RULES`);
  - registry agreement tests: every installed rule has an evaluator, every evaluator has an installed rule, every evidence source has a loader;
  - an upgrade test reproducing the lab history (V001-V016, manual seed, remaining migrations) and asserting V021 changes nothing there.

The tests were confirmed to fail before V021 and to catch deliberate regressions in V021.

Run all tests from the repository root (requires PostgreSQL `initdb`/`pg_ctl`, see the test module docstrings):

`python -B -m unittest discover -s tests -p "test_*.py" -v`

### Rule: Dictionary changes go through migrations

Every Dictionary change (assessment, rule, threshold, evidence requirement) is made by a migration. Manual SQL against the lab repository is for experiments only and must either be reverted or turned into a migration in the same working session. When a migration adds or changes a rule, `EXPECTED_RULES` in `tests/test_intelligence_dictionary.py` is updated in the same change.

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

Verified in the lab on 2026-10-05 (target 1, Patroni cluster) after the registry refactor. Every rule was run in a clean state, a problem state and a recovery state with fresh evidence.

| Rule | Clean | Problem | Recovery | How the problem was produced |
| --- | --- | --- | --- | --- |
| PG-CONN-001 | no finding (run 17) | WARNING (run 18) | no finding (run 20) | `BEGIN; SELECT 1/0;` left open on the primary |
| PG-TRAN-001 | no finding (run 21) | WARNING at 372 s (run 22), CRITICAL at ~950 s (run 23) | no finding | `BEGIN; SELECT 1;` left open on the primary |
| PG-TRAN-002 | no finding (runs 21-23 and recovery) | not produced | - | lab XID age cannot realistically reach the thresholds; covered by evaluator unit tests (planned) |
| PG-REP-001 | no finding (run 25) | WARNING (run 26) | no finding | controlled evidence: test slot row with `wal_status = extended` |
| PG-REP-002 | no finding (run 25) | CRITICAL (run 26) | no finding | controlled evidence: test slot row with `wal_status = lost` |

Finding text, observed value/unit and subject were checked for each problem finding.

Controlled evidence means rows named `keystone_test_*` were inserted into the latest real `postgresql.replication_slot_snapshot` (same `captured_at`) and deleted after the test. This verifies the engine, evidence loading, freshness and both evaluators, but not the collector reading a real `extended` or `lost` slot. A real slot test is planned on a snapshot of the lab VMs.

Runs are started with `python -m repository.intelligence.assessment_engine --assessment <assessment_key> --target <target_id>`; without arguments the engine runs `PG_CONNECTION_HEALTH` for target 1.

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

### 5. Migration checksums are recorded but not verified

The installer stores each migration's checksum in `keystone.migration_history` but does not compare it with the file on later runs. An applied migration file can change without any warning, so "applied migrations are immutable" is a convention, not an enforced rule.

### 6. Migration checksums depend on line endings

The checksum is a SHA-256 of the raw file bytes. A Windows checkout (CRLF) and a Linux checkout (LF) of the same commit produce different checksums. The lab repository was installed from Windows. Issues 5 and 6 should be solved together; changing the checksum calculation affects checksums already stored in existing repositories and needs a deliberate migration path.

### 7. Migration header Description is limited to 500 characters

The installer stores the header `Description` in `keystone.migration_history`, a `VARCHAR(500)` column. A longer description fails the installation. Keep the header description short and put detailed rationale in a separate SQL comment block (see V021).

### 8. Empty evidence vs missing evidence

Some collectors legitimately return zero rows (for example `PG_REPLICATION_SLOTS` on a server without replication slots). Evidence loaders read the latest captured rows, so "collected, nothing to report" is indistinguishable from "never collected" and is treated as missing evidence. Part of the open decision in issue 2.

### 9. Findings can persist after recovery within the freshness window

The engine evaluates the latest evidence that is still within `max_age_seconds`. If the condition is resolved but no new evidence has been collected, the old evidence still produces the finding. Observed in run 19: the aborted transaction was rolled back but the collector had not run again, so PG-CONN-001 still reported WARNING. Correct behaviour for the current model, but it must be documented in the Rule Catalog and considered when a health check triggers collection.

### 10. PG-TRAN-001 does not cover aborted idle transactions

PG-TRAN-001 matches `state = 'idle in transaction'` only. A session in `idle in transaction (aborted)` is never reported as a long idle transaction, however long it stays open; it only appears in PG-CONN-001 as a count without duration. Decide whether this is intended before writing the Rule Catalog entry.

### 11. Manual collection workflow is error-prone

A lab regression currently requires inserting a queue row, running the worker and running the engine by hand. A skipped queue insert produced a misleading result (run 19). This supports a later "run health check" entry point that collects the required evidence before evaluating. Not an MVP engine change by itself.

## Active Work

Current checkpoint: the five-rule Engineering Intelligence engine is regression-tested in the lab and covered by automated tests; next is MVP Plan Phase 0.

Done:

- Registry refactor verified against the repository: both registries complete, single evaluator contract, no leftover dispatch code.
- Clean-install Dictionary bug fixed (V021) and covered by automated tests, including registry completeness. V021 verified as a no-op on the lab repository.
- Engine command line: `--assessment` and `--target` select what runs; the file no longer needs editing.
- Lab regression of all five rules after the refactor (see Verification status).
- Evaluator and freshness unit tests; threshold matching made independent of threshold order.
- Product direction and MVP Plan recorded in the documentation vault (Product Strategy → Usage Scenarios, ADR-0013, MVP Plan).

Immediate work sequence (MVP Plan, Phase 0 — see `docs/KeyStone/02 - Roadmap/MVP Plan.md`):

1. Create the Engineering Intelligence Rule Catalog in the documentation vault, including issues 9 and 10.
2. Assessment Result model: persist HEALTHY / ATTENTION_REQUIRED / INSUFFICIENT_EVIDENCE per rule and run. This implements the outcome model already defined in the architecture documents (Health Assessment Playbook, Reference Architecture, ADR-0010) and resolves issues 2 and 8; it is an implementation task, not an open design question.
3. Fix assessment-run exception handling. Note: the engine does not commit explicitly and the repository connection rolls back on exception, so with the current code a failed run may leave no row at all rather than a RUNNING row. Run 16 is missing from the lab sequence and may be such a case; verify before designing the fix.

Then Phase 1 (one-command health check and report) and Phase 2 (scheduler, finding lifecycle, finding-driven notification). The threshold model is revisited with the first rule that needs multiple parameters.

Planned, not blocking the MVP engine:

- Real replication slot test (`extended` / `lost`) on a snapshot of the lab VMs, to verify the collector path.

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
