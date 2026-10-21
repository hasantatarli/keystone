# Keystone Development Status

Last updated: 2026-10-09

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

Six real PostgreSQL rules are currently implemented. The Rule Catalog (`docs/KeyStone/06 - Engineering Intelligence/Rule Catalog.md`) documents each of them.

| Rule | Assessment | Evidence | Result logic |
| --- | --- | --- | --- |
| PG-TRAN-001 | PG_TRANSACTION_HEALTH | PG_ACTIVITY_SNAPSHOT | Long idle transaction; idle time since `state_change`, WARNING 300 s / CRITICAL 900 s |
| PG-TRAN-003 | PG_TRANSACTION_HEALTH | PG_ACTIVITY_SNAPSHOT | Long-running transaction; transaction age in any non-aborted state, WARNING 30 min / CRITICAL 1 h |
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

All commands with their variations (agent, worker, engine, installer, credential tool, tests, configuration and check queries): `docs/KeyStone/07 - Operations/Command Reference.md`.

Runs are started with `python -m repository.intelligence.assessment_engine --assessment <assessment_key> --target <target_id>`; without arguments the engine runs `PG_CONNECTION_HEALTH` for target 1.

Keystone Agent (ADR-0015): `python -m repository.agent.agent [--max-workers 20] [--poll-seconds 10]` runs continuously. The agent holding the scheduler advisory lock queues `SCHEDULED` collector assignments on a clock-aligned grid (a slot missed by a long run is skipped; one catch-up run after downtime); every agent runs queued tasks in a continuous pool, limited per target by `target.max_concurrent_tasks` (V025). Schedule lag is in `collector_run_history.scheduled_at` vs `started_at`. Stop with Ctrl+C or SIGTERM. Linux service example: `deploy/systemd/keystone-agent.service`. `python -m repository.worker.worker` still drains the queue once and exits.

Technical logs (ADR-0014): engine, agent and worker write their console output also to `logs/<component>.log` (rotating; directory overridable with `KEYSTONE_LOG_DIR`), and WARNING and above to `keystone.event_log`. The worker logs one line per task start and end; collected rows only at DEBUG (`KEYSTONE_LOG_LEVEL=DEBUG`; PowerShell: `$env:KEYSTONE_LOG_LEVEL = "DEBUG"`):

`SELECT logged_at, level, component, message, context FROM keystone.event_log ORDER BY logged_at DESC LIMIT 20;`

## Known Issues / Open Design Decisions

### 1. Assessment run failure handling — resolved by V023 / ADR-0014

The run row is now committed first; engine failures end FAILED with `status_message`, rule failures end that rule as ERROR and the run as PARTIAL. Original note:


An exception during evaluation can currently leave an `assessment_run` in RUNNING state. This was observed during refactor testing. The engine needs explicit exception handling so technical execution failures finish the run as FAILED before the exception is propagated or reported.

### 2. Assessment outcome vs technical status — resolved by V023 / ADR-0014

Outcomes are persisted per rule in `keystone.assessment_result`. Original note:


A rule can be skipped because required evidence is missing or stale while the assessment run still finishes with status SUCCESS.

SUCCESS currently means technical execution success; it must not be interpreted as a healthy database. We need an explicit MVP decision for representing insufficient evidence without overloading technical run status.

### 3. Threshold model

The current `rule_threshold` model supports one threshold value per rule/severity. This works for the first five rules but will become limiting for rules that require multiple metrics, such as a vacuum rule combining dead tuple count and ratio.

Do not introduce a generic DSL. Revisit the smallest useful extension, such as named metrics or rule parameters, when implementing the next rule that genuinely needs it.

### 4. Multi-source evaluators — resolved by PG-CAP-001 (2026-10-20)

Rules with several evidence sources receive `{evidence_source: rows}`; single-source evaluators keep receiving their rows. Every declared source is checked for freshness.

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

### 12. Proxy or firewall idle timeouts cut long collector queries

Found 2026-10-14 (PR #14 lab lock test): the lab target connection goes through HAProxy, which closes connections idle for 50 s. A collector query that waits without returning data (a lock wait, or size functions on a large database) is cut after 50 s; for DATABASE-scoped collectors the affected database fails and the run ends `PARTIAL_SUCCESS`. TCP keepalive does not prevent this (the proxy host answers the probes). Short collectors are not affected. Options to decide: collectors connect to nodes directly, the customer raises the proxy timeout for the Keystone user, or an installation checklist item. Related: short `lock_timeout` for collector sessions (hardening backlog).

## Active Work

Current checkpoint: MVP Plan Phase 0 complete; next is Phase 1 (scheduling, then the one-command health check and report).

Done:

- Registry refactor verified against the repository: both registries complete, single evaluator contract, no leftover dispatch code.
- Clean-install Dictionary bug fixed (V021) and covered by automated tests, including registry completeness. V021 verified as a no-op on the lab repository.
- Engine command line: `--assessment` and `--target` select what runs; the file no longer needs editing.
- Lab regression of all five rules after the refactor (see Verification status).
- Evaluator and freshness unit tests; threshold matching made independent of threshold order.
- Product direction and MVP Plan recorded in the documentation vault (Product Strategy → Usage Scenarios, ADR-0013, MVP Plan).
- Engineering Intelligence Rule Catalog: `docs/KeyStone/06 - Engineering Intelligence/Rule Catalog.md`.

Phase 0 is complete (2026-10-14): assessment results and rule-level failure isolation (V023), evaluation time parameter, shared logging with `keystone.event_log` (V024), concise code hints.

Phase 1, step 1 done (2026-10-14, PR #11, #12, lab-verified): Keystone Agent with generic scheduler and collector scheduling; fixed grid, continuous pool, per-target limit and schedule lag (V025); worker logging through the shared logger.

Phase 1, step 2 done (2026-10-14, PR #13, lab-verified): scheduled assessments (V026) with 30 s offset and no catch-up at start, Dictionary defaults and `apply_default_assessment_schedules`, `schedule_consistency_warning`, one log line per assessment run.

Hardening done (2026-10-14, PR #14, lab-verified): TCP keepalive on target connections; long-running task warning (V027, `expected_max_seconds`); per-database error text in run history.

One-command health check done (2026-10-14, PR #15, lab-verified): `python -m repository.healthcheck.health_check --target <id>`; V028 (`health_check`, `health_check_collection`, `assessment_run.health_check_id`); SYSTEM target includes its NODE targets; first lab run collected 9 tasks in 4.5 s, all six rules evaluated.

Report review decisions (2026-10-19, Hasan + external review):
- Reports claim only what was checked: HEALTHY texts state the check and its limit, filled from the thresholds used (stored per result, V030). What a rule does not evaluate is not listed in customer reports; it stays in the Rule Catalog known limitations and drives new rules.
- Next rule: replication lag / replica connection state from `PG_REPLICATION_STATUS` (already collected, not evaluated).
- Two-level reporting: per-target report plus an overview of all targets of a customer as the single entry point (one command writes the overview and the per-target reports to one folder; rows link to the reports). Overview summarizes existing assessment results (no second evaluation), shows freshness, keeps node-level problems visible. Needs a customer concept: ADR-0016. HTML first; a web application for DBAs doing live follow-up later, reusing the same overview query.
- Executive inventory per server for small systems; for large estates only totals and exceptions (disk above limits, replicas smaller than the primary).

Report, inventory and rule coverage (2026-10-19/20, PR #16, #17 lab-verified and merged):
- HTML report with executive / technical tabs, TR/EN Dictionary texts (V029, V030), timestamped files, `--report` on the health check.
- Per-server inventory; PG-CAP-001 Data Disk Usage (V031), usage like `df` (root-reserved blocks count as used). Judgements are rules; the inventory only displays.
- Executive tiles count checks (they add up); affected areas name the problem.
- **PostgreSQL V1 Assessment Catalogue** (Service Catalog → Health Assessment): 62 checks, priorities P1 → P3, pg_collector coverage, review decisions (configuration recommendations, backup method detection, conscious choices are WARNING).

In progress — PR #18 (draft), replication and HA rules PG-REP-003…006 (V032, PG014):
- Lab 2026-10-20: clean state and stopped replica (PG-REP-004 + PG-REP-005) as expected. PG-REP-006 not simulable with Patroni (it manages `synchronous_standby_names`); covered by tests.
- **Open:** the lag test (replay paused on a replica, writes on the primary) produced no PG-REP-003 finding. Suspected: `replay_lag` stops growing when replay is stuck. Next: Hasan runs `pg_stat_replication` with WAL bytes behind while replay is paused; then add a WAL-bytes condition (proposal 256 MB / 1 GB), which needs a second unit per rule (Known Issue 3).
- **Agreed direction:** problem cards in bullets — "What is happening" (one sentence), "Likely causes" (list, new rule text type CAUSES), "Why it matters", "What to do" (steps). Rewrite TR/EN texts of all rules. To be confirmed by Hasan before implementation (likely in PR #18).

Rule batches from the Assessment Catalogue (2026-10-21):
- PR #18 merged: PG-REP-003…006 (V032–V035), problem cards with causes and steps (CAUSES text type), lag beyond an intended apply delay; the observed value is always what was measured (Rule Catalog principle).
- PR #19 lab-verified: PG-CONF-001/002/004, PG-CONN-002 (V036, V037). Patroni resumes paused replay; `pg_wal_replay_pause()` cannot simulate lag there.
- Improvement noted: PG-CONF-001 should show the pending new value (`pg_file_settings`) and setting values in readable units (32768 × 8 kB → 256 MB). Finding sentences are still English only in the Dictionary (`finding_template`); make them TR/EN.

Next (MVP Plan Phase 1):

1. HTML report from a health check (Turkish/English frame): first draft in PR #16 (draft), lab report generated 2026-10-14. To discuss next session:
   - Plain-language results ("explain it to a non-DBA"): per rule a healthy statement, meaning / likely cause, and impact, stored in the Dictionary per language (rule text table: rule, language, text type, text); report groups rules by topic (replication, transactions, connections…) with one plain sentence each. Revisits the 2026-10-14 decision that rule texts stay English. Claude drafts TR/EN texts for the six rules, Hasan reviews as DBA.
   - Two report levels (Hasan, 2026-10-14): **C-level** (CTO/CEO: visuals, numbers, short sentences, which business areas are affected, decisions) and **technical** (DBA / IT manager: rule details, evidence, collection status). Same health check data, two renderings; decide whether one file with two parts or two files.
   - Later, Engineering Intelligence: combine findings into one diagnosis (advanced RCA).
   - Open report questions: logo / company name, customer name, extra sections, PDF output.
   - Several independent systems of one customer: per-system report plus an overview page; needs a customer concept in the data model.
2. Default collector intervals from collector header metadata.
3. Windows service setup for the agent.

Small gaps noted: `collector_assignment` has no creation time / creator (needed when the web interface edits assignments).

Hardening backlog:

- Later (Engineering Intelligence): known activity windows, for example a weekend backup, as context so that long runs inside them are not reported. Related to the deferred time windows in ADR-0015.
- Collector target sessions: short `lock_timeout`; shorter `statement_timeout` for `PG_TABLE_CAPACITY` (relation size functions take AccessShareLock on every relation; a concurrent DDL would queue other sessions behind it). Values to be decided from field experience.

Planned, not blocking the MVP engine:

- Real replication slot test (`extended` / `lost`) on a snapshot of the lab VMs, to verify the collector path.

The five-rule checkpoint was completed on 2026-10-05. New rules follow the checklist in the Rule Catalog (catalog entry, migration, evaluator, `EXPECTED_RULES`, unit tests, lab verification).

## Rule Catalog

The Engineering Intelligence Rule Catalog documents each rule's purpose, evidence, freshness, criteria, thresholds, subject, limitations and verification, plus candidate rules: `docs/KeyStone/06 - Engineering Intelligence/Rule Catalog.md`. Update it together with the migration and `EXPECTED_RULES` whenever a rule changes.

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

### Branching rule (agreed 2026-10-05)

- **Code changes** (Python, SQL migrations, collectors, tests): work on a branch, run the full automated test suite, open a pull request, verify in the lab when the change affects runtime behaviour, then merge. Unverified code is never pushed to `main`.
- **Documentation-only changes** (this file, the documentation vault): may be committed directly to `main`. They need no lab verification and the branch/PR cycle adds no safety.

Run the full test suite from the repository root before opening a code pull request:

`python -B -m unittest discover -s tests -p "test_*.py" -v`

Code comments are short hints (1–2 lines) that say what a block does and point to where the reasoning lives (ADR, Rule Catalog), so someone editing by hand can orient quickly. Detailed rationale belongs in the documentation vault, not in docstrings. Avoid comments that merely restate obvious syntax.
