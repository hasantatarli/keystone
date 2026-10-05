# Engineering Intelligence Rule Catalog

**Status:** Current  
**Last Updated:** 2026-10-05  
**Provider:** PostgreSQL (15+)

## Purpose

This catalog explains, in engineering terms, what each Keystone rule detects, why, from which evidence, and what it deliberately does not detect.

It is documentation, not configuration. The machine-readable source of truth is:

- the Dictionary, seeded by migrations under `repository/migrations/core/` (V016–V021),
- the evaluators in `repository/intelligence/assessment_engine.py`,
- the expected Dictionary contract in `tests/test_intelligence_dictionary.py` (`EXPECTED_RULES`).

When a rule changes, the migration, the test contract and this catalog change together.

---

# How Rules Work

## Configuration in data, engineering logic in code

| Lives in the Dictionary | Lives in Python |
| --- | --- |
| Rule identity, name, assessment | The condition (what counts as a problem) |
| Evidence requirements and freshness | Calculations and correlations |
| Thresholds and default severity | Selection of the reached threshold |
| Finding template and recommendation | Subject identification |

A generic rule language is intentionally not used. A rule's engineering logic is a small, testable Python evaluator registered in `RULE_EVALUATORS`.

## Evaluation sequence

For each enabled rule of an assessment:

1. Load the rule's evidence requirements.
2. Load each evidence source once per run (`EVIDENCE_LOADERS`) and reuse it for other rules in the same run.
3. Validate freshness: the newest evidence row must be no older than `max_age_seconds` at evaluation time.
4. If required evidence is missing or stale, the rule is **not evaluated**.
5. Otherwise call the evaluator, which returns zero or more findings.
6. Persist each finding with the rule's finding template and recommendation.

## Common semantics

- **Latest snapshot only.** Loaders read the most recent captured snapshot for the target. Rules do not yet use history.
- **Thresholds are inclusive.** A value equal to a threshold reaches it (`>=`).
- **Highest reached threshold wins**, independent of the order thresholds are stored or loaded. Thresholds with a different unit are ignored.
- **Rules without thresholds** use `rule_definition.default_severity`.
- **One finding per affected subject** (session, database, slot or system), not one per rule.
- **Severities:** INFO, WARNING, CRITICAL.

## Known general limitations

These apply to every rule and are tracked in `docs/DEVELOPMENT_STATUS.md`:

- **Assessment outcome is not yet persisted.** A rule skipped for missing or stale evidence is only reported on the console, and a run with skipped rules still ends SUCCESS. The architecture requires HEALTHY / ATTENTION_REQUIRED / INSUFFICIENT_EVIDENCE per check; this is MVP Plan Phase 0.
- **Empty evidence looks like missing evidence.** A collector that legitimately returns no rows (for example no replication slots) cannot be distinguished from a collector that never ran.
- **Findings can persist after recovery within the freshness window.** If a condition is resolved but no new evidence has been collected, the previous snapshot still produces the finding until fresh evidence arrives or the evidence becomes stale.
- **No finding lifecycle yet.** Every run creates new findings; the same condition seen in consecutive runs is not linked. Required for continuous assessment (MVP Plan Phase 2).

---

# PG_TRANSACTION_HEALTH — Transaction Health

## PG-TRAN-001 — Long Idle Transaction

**Purpose**  
Detect client sessions that keep a transaction open while doing nothing. Such sessions can hold locks and keep the xmin horizon back, which prevents VACUUM from removing dead tuples. The damage grows with time, so the rule measures duration.

| | |
| --- | --- |
| Evidence | `PG_ACTIVITY_SNAPSHOT` (`postgresql.activity_snapshot`), required |
| Freshness | 600 seconds |
| Condition | `backend_type = 'client backend'` and `state = 'idle in transaction'` and `state_change` is not null |
| Metric | `captured_at - state_change`: how long the session has been idle, in seconds |
| Thresholds | WARNING ≥ 300 s, CRITICAL ≥ 900 s |
| Subject | SESSION (pid) |
| Finding | Session {pid} has been idle in transaction for {duration_seconds} seconds. |
| Recommendation | Review the application transaction lifecycle and determine why the transaction remains open. |

**Design notes**

- The metric is **idle time**, measured from `state_change` (the moment the session entered `idle in transaction`). A transaction that worked for ten minutes and has been idle for one minute is idle for one minute. The question this rule answers is "did the application leave a transaction open and stop talking to the database?"
- Until 2026-10-05 the metric was transaction age (`captured_at - transaction_start`). It was changed because a long working transaction that had only just become idle was reported as a long idle transaction.
- Transaction age regardless of state is a different engineering question (a transaction holding the xmin horizon for a long time, even if it keeps issuing short statements). It is a separate rule candidate: **Long-Running Transaction**.
- Sessions in `idle in transaction (aborted)` are deliberately excluded. They are covered by PG-CONN-001 (see below).

**Known limitations**

- Only state at collection time is seen; a transaction that opens and closes between collections is invisible.
- Aborted subtransactions inside a savepoint can keep the outer transaction's locks and xmin. Such sessions show `idle in transaction (aborted)`, are excluded here, and PG-CONN-001 reports them only as a count. Candidate post-MVP rule: **Long Resource-Retaining Aborted Transaction**, using `backend_xmin` / `backend_xid`, which `PG_ACTIVITY_SNAPSHOT` already collects.
- Connections through a transaction-pooling proxy may hide the client that owns the transaction.

**Verification**  
Lab 2026-10-05 (with the earlier transaction-age metric; the test sessions became idle immediately after BEGIN, so idle time and transaction age were equal): WARNING at 372 s, CRITICAL at ~950 s, recovery after ROLLBACK. Unit tests cover boundaries (299.9 / 300 / 900 s), filters, aborted-session exclusion, and idle time versus transaction age.

---

## PG-TRAN-002 — Database Transaction ID Wraparound Risk

**Purpose**  
Detect databases whose transaction ID age is approaching the wraparound limit. If VACUUM cannot advance the freeze horizon, PostgreSQL eventually stops accepting write transactions to protect data.

| | |
| --- | --- |
| Evidence | `PG_TRANSACTION_WRAPAROUND` (`postgresql.transaction_wraparound_snapshot`), required |
| Freshness | 86400 seconds (XID age changes slowly) |
| Condition | Every database row is evaluated |
| Metric | `xid_age` (age of `datfrozenxid`) |
| Thresholds | WARNING ≥ 1,500,000,000, CRITICAL ≥ 1,800,000,000 transactions |
| Subject | DATABASE |
| Finding | Database {database_name} has a transaction ID age of {xid_age}. |
| Recommendation | Investigate freeze progress and vacuum activity; ensure VACUUM can advance the freeze horizon. |

**Design notes**

- Thresholds are Keystone engineering defaults, not PostgreSQL limits. They are set well below the hard limit of about 2.1 billion to leave time to act.

**Known limitations**

- Thresholds are absolute. They are not yet evaluated relative to the effective `autovacuum_freeze_max_age` (default 200 million), so a database that is far beyond its configured freeze age but below 1.5 billion is not reported. The 2026-09-21 evidence matrix calls for severity relative to configuration; this needs the configuration snapshot as a second evidence source.
- MultiXact age (`mxid_age`) is collected but not evaluated. Separate rule candidate (roadmap PG-029).
- Relation-level wraparound evidence is collected but not evaluated; the rule reports databases, not the tables holding the horizon back.

**Verification**  
Not reproducible in the lab. Unit tests cover the 1.5 / 1.8 billion boundaries and per-database evaluation. Earlier lab tests used temporarily lowered thresholds.

---

# PG_REPLICATION_HEALTH — Replication Health

Both rules evaluate `pg_replication_slots.wal_status` and use `default_severity` instead of thresholds.

| `wal_status` | Meaning | Rule |
| --- | --- | --- |
| `reserved` | Required WAL is within `max_wal_size` | none |
| `extended` | Required WAL exceeds `max_wal_size` but is still retained | PG-REP-001 |
| `unreserved` | Required WAL is no longer guaranteed and may be removed at the next checkpoint | PG-REP-002 |
| `lost` | Required WAL has been removed; the slot can no longer be used | PG-REP-002 |

## PG-REP-001 — Replication Slot WAL Retention Pressure

**Purpose**  
Detect slots whose consumer is falling behind enough that WAL is retained beyond the normal size boundary. Early warning for disk growth on the primary and for a slot heading towards `unreserved`.

| | |
| --- | --- |
| Evidence | `PG_REPLICATION_SLOTS` (`postgresql.replication_slot_snapshot`), required |
| Freshness | 600 seconds |
| Condition | `wal_status = 'extended'` |
| Severity | WARNING (default severity) |
| Subject | REPLICATION_SLOT (slot name) |
| Finding | Replication slot {slot_name} has WAL status {wal_status}. |
| Recommendation | Review the consumer and WAL retention configuration; verify the consumer is progressing. |

## PG-REP-002 — Replication Slot WAL Unavailable

**Purpose**  
Detect slots whose required WAL is no longer safe or already gone. The consumer may be unable to continue and may need to be rebuilt.

| | |
| --- | --- |
| Evidence | `PG_REPLICATION_SLOTS`, required |
| Freshness | 600 seconds |
| Condition | `wal_status IN ('unreserved', 'lost')` |
| Severity | CRITICAL (default severity) |
| Subject | REPLICATION_SLOT (slot name) |
| Finding | Replication slot {slot_name} has WAL status {wal_status}. |
| Recommendation | Investigate the consumer immediately; verify whether the slot can recover or must be recreated. |

**Known limitations (both rules)**

- `wal_status` reflects size boundaries only. An inactive slot that is still `reserved` (consumer gone, WAL accumulating slowly) is not reported. Inactive / stale slot detection is a separate rule candidate from the 2026-09-21 evidence matrix.
- A system without replication slots produces no evidence rows, which is currently treated as missing evidence (see general limitations).
- Replication lag and replica connectivity are collected by `PG_REPLICATION_STATUS` but not yet evaluated.

**Verification**  
Lab 2026-10-05 with controlled evidence: test slot rows with `extended` and `lost` inserted into a real snapshot produced WARNING and CRITICAL; real `reserved` slots produced no findings. A test against real `extended` / `lost` slots is planned on lab VM snapshots to also verify the collector path. Unit tests cover all five status values.

---

# PG_CONNECTION_HEALTH — Connection Health

## PG-CONN-001 — Aborted Idle Transaction Connections

**Purpose**  
Detect client connections left in a failed transaction that was never rolled back. This indicates an application or connection-pool defect: the connection is unusable until ROLLBACK and may be handed to other application requests in a broken state.

| | |
| --- | --- |
| Evidence | `PG_CONNECTION_ACTIVITY` (`postgresql.connection_activity_snapshot`, system row), required |
| Freshness | 600 seconds |
| Metric | `idle_in_transaction_aborted_connections` |
| Threshold | WARNING ≥ 1 connection |
| Subject | SYSTEM (target) |
| Finding | {connection_count} client connection(s) are idle in an aborted transaction state. |
| Recommendation | Review the transaction lifecycle and connection handling; ensure failed transactions are rolled back. |

**Design notes**

- A single occurrence is actionable, therefore the threshold is 1.
- The rule measures presence, not duration. In a top-level failed transaction PostgreSQL has already released locks and the snapshot; the session only waits for ROLLBACK. The risk is application correctness rather than growing database impact, so duration does not raise severity.

**Known limitations**

- Reports a count for the whole system, not the individual sessions. Session details are available in `PG_ACTIVITY_SNAPSHOT`.
- Savepoint case: see PG-TRAN-001 limitations and the Long Resource-Retaining Aborted Transaction candidate.

**Verification**  
Lab 2026-10-05: no finding at 0, WARNING with one `BEGIN; SELECT 1/0;` session, no finding after ROLLBACK and fresh evidence. Unit tests cover 0 and 1.

---

# Adding a Rule

1. Write the catalog entry first: purpose, evidence, condition, metric, thresholds, subject, limitations.
2. Confirm the evidence is collected; if not, the collector or migration comes first.
3. Add the Dictionary rows in a **migration** — never by hand in a repository.
4. Add the evaluator and register it in `RULE_EVALUATORS`; add the loader to `EVIDENCE_LOADERS` if the source is new.
5. Update `EXPECTED_RULES` in `tests/test_intelligence_dictionary.py` and add evaluator unit tests, including threshold boundaries.
6. Run the full test suite, open a pull request, verify in the lab (clean, problem and recovery states where feasible).
7. Record the verification result in this catalog.

# Candidate Rules

Not implemented; recorded so they are not lost.

| Candidate | Source | Evidence available |
| --- | --- | --- |
| Long-Running Transaction (transaction age regardless of state) | PG-TRAN-001 design notes; 2026-09-21 evidence matrix | Yes (`PG_ACTIVITY_SNAPSHOT.transaction_start`) |
| Long Resource-Retaining Aborted Transaction | Savepoint limitation above | Yes (`PG_ACTIVITY_SNAPSHOT`) |
| MultiXact wraparound risk | PG-TRAN-002 limitation, roadmap PG-029 | Yes (`mxid_age`) |
| XID age relative to `autovacuum_freeze_max_age` | PG-TRAN-002 limitation | Yes (wraparound + configuration snapshots) |
| Inactive / stale replication slot | 2026-09-21 evidence matrix | Yes (`PG_REPLICATION_SLOTS`) |
| Replication lag / replica disconnected | 2026-09-21 evidence matrix | Yes (`PG_REPLICATION_STATUS`) |
| Connection capacity vs `max_connections` | 2026-09-21 evidence matrix | Yes (connection activity + configuration) |
| Dead tuple pressure, analyze freshness | 2026-09-21 evidence matrix | Yes (`PG_VACUUM_ANALYZE`); needs multi-parameter thresholds |
| Pending restart configuration | 2026-09-21 evidence matrix | Yes (`PG_CONFIGURATION_SNAPSHOT`) |
| Filesystem capacity | 2026-09-21 evidence matrix | Yes (`PG_HOST_SNAPSHOT` storage) |
