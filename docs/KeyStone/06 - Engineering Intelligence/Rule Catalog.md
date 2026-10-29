# Engineering Intelligence Rule Catalog

**Status:** Current  
**Last Updated:** 2026-10-29  
**Provider:** PostgreSQL (15+)

## Purpose

This catalog explains, in engineering terms, what each Keystone rule detects, why, from which evidence, and what it deliberately does not detect.

It is documentation, not configuration. The machine-readable source of truth is:

- the Dictionary, seeded by migrations under `repository/migrations/core/` (V016–V044),
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
4. If required evidence is missing or stale, the rule is **not evaluated** and its result is INSUFFICIENT_EVIDENCE.
5. Otherwise call the evaluator, which returns zero or more findings. An evaluator that finds the evidence cannot answer the rule (for example no primary among the collected nodes) raises `InsufficientEvidence`; the result is INSUFFICIENT_EVIDENCE with a coded reason (V041).
6. Persist each finding with the rule's finding template and recommendation, and the rule's result (HEALTHY or ATTENTION_REQUIRED with the highest severity).

Each rule runs in its own transaction. If anything fails, the rule's partial work is rolled back and its result is ERROR with the error message.

## Common semantics

- **Latest snapshot only.** Loaders read the most recent captured snapshot for the target (for NODE-scoped evidence, per node). Rules do not yet use history.
- **Every row is judged on its own age** (2026-10-21). Rows older than the rule's freshness limit are dropped before evaluation, so a node whose collection failed is not judged on its last snapshot. A health check additionally ignores the rows of every target and collector it failed to collect (`health_check_collection` status other than SUCCESS / PARTIAL_SUCCESS): it judges only what it collected itself. The report shows context on the same basis. Collection status, not capture time, decides, because capture times come from the target clocks (lab: VM clocks 3 minutes behind the laptop). Lab case: postgre-1 was unreachable and its 1.5-hour-old settings produced findings.
- **The current primary** is the node not in recovery with the newest instance inventory; after a failover the old primary's row can linger.
- **The observed value is what was measured; thresholds only decide the severity** (Hasan, 2026-10-21). A finding never reports a derived or adjusted figure as if it had been measured. When a rule compares an adjusted value (for example lag beyond an intended delay, usage beyond a reserve), the finding shows the measured value, the adjustment and the compared part separately. Applies to every rule.
- **Thresholds are inclusive.** A value equal to a threshold reaches it (`>=`).
- **Highest reached threshold wins**, independent of the order thresholds are stored or loaded. Thresholds with a different unit are ignored.
- **Rules without thresholds** use `rule_definition.default_severity`.
- **Rule parameters** (V039, 2026-10-26): besides the severity thresholds on the main metric, a rule can have any number of named parameters in `keystone.rule_parameter` (preconditions such as a minimum row count, limits such as a large-table count). The evaluator combines them in code; there is no rule expression language. Parameters used are stored per result (`parameters_used`) and shown in the technical report.
- **One finding per affected subject** (session, database, slot or system), not one per rule.
- **Severities:** INFO, WARNING, CRITICAL.

## Known general limitations

These apply to every rule and are tracked in `docs/DEVELOPMENT_STATUS.md`:

- **Outcomes are persisted per rule (since V023, ADR-0014).** Every evaluated rule records HEALTHY, ATTENTION_REQUIRED, INSUFFICIENT_EVIDENCE (with the evidence source and age) or ERROR in `keystone.assessment_result`. A rule that fails technically does not stop the others; the run then ends PARTIAL.
- **Empty evidence looks like missing evidence** for collectors that return only detail rows (for example no replication slots). Collectors written since V041 always return a SYSTEM row, so "none" is evidence (`PG_PREPARED_TRANSACTIONS`); older collectors are not changed yet.
- **Findings can persist after recovery within the freshness window** when an assessment runs on scheduled evidence. A health check collects fresh evidence first and judges only what it collected, so it is not affected.
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
- Transaction age regardless of state is a different engineering question (a transaction holding the xmin horizon for a long time, even if it keeps issuing short statements). It is covered by **PG-TRAN-003 Long-Running Transaction**.
- Sessions in `idle in transaction (aborted)` are deliberately excluded. They are covered by PG-CONN-001 (see below).

**Known limitations**

- Only state at collection time is seen; a transaction that opens and closes between collections is invisible.
- Aborted subtransactions inside a savepoint can keep the outer transaction's locks and xmin. Such sessions show `idle in transaction (aborted)`, are excluded here, and PG-CONN-001 reports them only as a count. Candidate post-MVP rule: **Long Resource-Retaining Aborted Transaction**, using `backend_xmin` / `backend_xid`, which `PG_ACTIVITY_SNAPSHOT` already collects.
- Connections through a transaction-pooling proxy may hide the client that owns the transaction.

**Verification**  
Lab 2026-10-05 (with the earlier transaction-age metric; the test sessions became idle immediately after BEGIN, so idle time and transaction age were equal): WARNING at 372 s, CRITICAL at ~950 s, recovery after ROLLBACK. Unit tests cover boundaries (299.9 / 300 / 900 s), filters, aborted-session exclusion, and idle time versus transaction age.

---

## PG-TRAN-003 — Long-Running Transaction

**Purpose**  
Detect client transactions that have been open for a long time, whatever the session is doing. An old transaction holds the xmin horizon and its locks: VACUUM cannot remove dead tuples created after it started, which leads to bloat, and other sessions may wait on its locks. This happens while the transaction keeps working as well as while it is idle.

| | |
| --- | --- |
| Evidence | `PG_ACTIVITY_SNAPSHOT` (`postgresql.activity_snapshot`), required |
| Freshness | 600 seconds |
| Condition | `backend_type = 'client backend'` and `transaction_start` is not null and `state <> 'idle in transaction (aborted)'` |
| Metric | `captured_at - transaction_start`: transaction age, in seconds |
| Thresholds | WARNING ≥ 1800 s (30 min), CRITICAL ≥ 3600 s (1 h) |
| Subject | SESSION (pid) |
| Finding | Session {pid} has had a transaction open for {duration_seconds} seconds (current state: {state}). |
| Recommendation | Identify the workload behind the transaction; long transactions hold the xmin horizon and locks. Consider smaller transactions and review application transaction boundaries. |

**Design notes**

- Thresholds are more tolerant than PG-TRAN-001 because legitimate long work (batch jobs, reporting, `pg_dump`) also matches. Such work really does hold the xmin horizon, so it is reported; the state in the finding text helps the engineer recognise it.
- **Overlap with PG-TRAN-001 is intentional.** A session idle in a transaction for a long time can match both rules: PG-TRAN-001 answers "did the application forget an open transaction?", PG-TRAN-003 answers "is a transaction holding back VACUUM?". Reporting may group findings for the same session later.
- Top-level aborted transactions are excluded: they have already released their snapshot and locks and are reported by PG-CONN-001.

**Known limitations**

- Only state at collection time is seen.
- Aborted subtransactions inside a savepoint keep the outer transaction's resources but are excluded together with all aborted sessions. See the Long Resource-Retaining Aborted Transaction candidate.
- Transactions opened by background workers or replication connections are not evaluated (client backends only). A standby with `hot_standby_feedback` can hold the primary's xmin through its replication slot; that is a replication concern, not covered here.
- Allow-listing of known long jobs is not supported; there are no per-target overrides yet.

**Verification**  
Unit tests: boundaries (1799.9 / 1800 / 3600 s), reversed threshold order, any non-aborted state measured, aborted / no-transaction / non-client excluded, transaction age vs. idle time. Clean-install contract updated. Lab 2026-10-14: WARNING at 1844.6 s with state active while PG-TRAN-001 reported nothing (session not idle).

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

## PG-REP-003 — Replication Lag

**Purpose**  
Detect replicas that apply the primary's changes late.

| | |
| --- | --- |
| Evidence | `PG_REPLICATION_STATUS` (replica rows of `pg_stat_replication` on the primary), required; `PG_CONFIGURATION_SNAPSHOT` and `PG_INSTANCE_INVENTORY` of the nodes, optional (V033) |
| Freshness | 600 seconds (status); optional evidence that is stale is treated as absent |
| Metric | `replay_lag` in seconds beyond the replica's `recovery_min_apply_delay`; NULL (caught up, primary idle) counts as 0 |
| Thresholds | WARNING ≥ 60 s, CRITICAL ≥ 300 s |
| Subject | REPLICA (application_name, else address) |
| Details | WAL not yet replayed (bytes), state, sync state |

**Design notes**  
Lab 2026-10-21: with `recovery_min_apply_delay = 5min` on a replica, `replay_lag` grew 37 s → 84 s → 143 s and WAL behind 174 → 321 MB, so the time metric follows a stuck replay. Such a deliberately delayed replica (protection against accidental deletes) is judged only on the lag beyond its delay. The finding still reports the measured lag as the observed value and shows the intended delay and the part beyond it separately (V035): "6 minutes behind, 1 minute beyond its intended delay of 5 minutes", never just "1 minute behind". `pg_wal_replay_pause()` cannot create lag under Patroni: Patroni resumes replay within seconds.

**Known limitations**  
Time thresholds only (one unit per rule); WAL bytes behind is shown, not judged. Replicas are matched to their node configuration by address. `replay_lag` is computed by the primary from replies; a replica that stopped replying is covered by PG-REP-004.

## PG-REP-004 — Replica Not Streaming

**Purpose**  
Detect servers known as replicas that do not receive changes from the primary.

| | |
| --- | --- |
| Evidence | `PG_REPLICATION_STATUS`, required (600 s); `PG_INSTANCE_INVENTORY` on every node, required (3600 s) |
| Condition | A node in recovery whose address is not among the primary's replication connections, or a connection not in `streaming` state |
| Severity | WARNING; CRITICAL when no known replica is streaming (no failover target left) |
| Subject | REPLICA (node name or application_name) |

**Design notes**  
Known replicas come from the instance inventory, so no expected topology has to be declared (2026-09-21 decision). Addresses are matched without prefix length; when a node's address is unknown the rule compares counts.

**Known limitations**  
Cascading replicas connected to another replica are reported as not connected. After a failover, inventory older than the freshness limit can name the wrong node; the health check always collects it fresh.

## PG-REP-005 — Inactive Replication Slot

| | |
| --- | --- |
| Evidence | `PG_REPLICATION_SLOTS`, required, 600 s |
| Condition | Permanent slot with `active = false` (temporary slots ignored) |
| Severity | WARNING (default severity) |
| Subject | REPLICATION_SLOT |

**Known limitations**  
No duration yet: a slot inactive for a few seconds during a replica restart is reported. PostgreSQL 17 `inactive_since` is a candidate improvement. Retained WAL beyond `max_wal_size` is PG-REP-001.

## PG-REP-006 — Synchronous Replication Without a Synchronous Standby

| | |
| --- | --- |
| Evidence | `PG_REPLICATION_STATUS` with `synchronous_standby_names` of the same server and moment (PG014), required, 600 s |
| Condition | `synchronous_standby_names` not empty and no replica in `sync` or `quorum` state |
| Severity | CRITICAL (commits wait) |
| Subject | SYSTEM |

**Design notes**  
Patroni with `synchronous_mode` clears the setting when no standby is available unless `synchronous_mode_strict` is on; the rule judges the effective setting, so both cases are handled.

**Verification (PG-REP-003…006)**  
Unit tests for every condition; repository test runs the real collector SQL, the worker persistence and the assessment end to end. Lab: pending.

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
- The rule measures presence, not duration. In a top-level failed transaction PostgreSQL has already released locks and the snapshot; the session only waits for ROLLBACK. It does not hold back VACUUM.
- The cost is **connection capacity and application correctness**:
  - the backend still occupies a `max_connections` slot;
  - behind a transaction-pooling proxy (for example PgBouncer in transaction mode) the server connection cannot be handed to another client until the transaction ends, so an aborted session pins a pool connection;
  - in an application-side pool, the same broken connection may be handed to another request, which then fails with "current transaction is aborted".
- Aggregate capacity impact belongs to the Connection Capacity candidate rule; this rule reports that the defect exists.

**Known limitations**

- Reports a count for the whole system, not the individual sessions. Session details are available in `PG_ACTIVITY_SNAPSHOT`.
- The finding does not say how long the oldest aborted session has been waiting, although the evidence contains it (`oldest_idle_in_transaction_aborted_state_change`). Candidate improvement: add it to the finding text without changing severity, so the engineer can tell a new occurrence from one that has been pinning a connection for hours.
- Savepoint case: see PG-TRAN-001 limitations and the Long Resource-Retaining Aborted Transaction candidate.

**Verification**  
Lab 2026-10-05: no finding at 0, WARNING with one `BEGIN; SELECT 1/0;` session, no finding after ROLLBACK and fresh evidence. Unit tests cover 0 and 1.

---

# PG_CAPACITY_HEALTH — Capacity Health

## PG-CAP-001 — Data Disk Usage

**Purpose**  
Detect nodes whose filesystem holding PostgreSQL's `data_directory` is filling up. A full data disk stops writes and can stop the database.

| | |
| --- | --- |
| Evidence | `PG_HOST_SNAPSHOT` (`postgresql.storage_snapshot`), required; `PG_CONFIGURATION_SNAPSHOT` (`data_directory`), required |
| Freshness | 3600 seconds (host), 86400 seconds (configuration) |
| Metric | used / (used + available) of the data disk, in percent (one decimal) — the same as `df` Use% |
| Thresholds | WARNING ≥ 80 %, CRITICAL ≥ 90 % |
| Subject | NODE (one finding per node) |
| Finding | The data disk {mount_point} on {node_name} is {used_percent}% full (data_directory {data_directory}). |
| Topic / categories | STORAGE; CAPACITY, AVAILABILITY |

**Design notes**

- First rule on NODE-scoped evidence and first rule with two evidence sources. Loaders read the target itself if it is a NODE, otherwise its active NODE children. Evaluators of multi-source rules receive `{evidence_source: rows}`; single-source evaluators are unchanged.
- The data disk is the mount with the longest mount point that contains `data_directory` as a whole directory (`/var/lib/pg` does not contain `/var/lib/pgsql`). The report inventory uses the same function, so the table and the rule always agree.
- Other mounts (`/`, `/boot`, backup disks) are not judged by this rule.
- Root-reserved blocks (ext4: 5 %) are not available to the postgres user, so they count as used. Lab 2026-10-20: used / size gave 77 % while `df` showed 82 % and PostgreSQL would fail at 100 % of the available space; used / (used + available) matches `df`.
- Introduced 2026-10-20 because the report showed disk usage as an inventory remark while the Capacity summary said "no problems found". Judgements are rules; the inventory only displays.

**Known limitations**

- Tablespaces outside `data_directory` and a separately mounted `pg_wal` are not evaluated.
- Nodes without host evidence (no SSH connection) are skipped while other nodes are evaluated; the HEALTHY text then covers only the evaluated nodes. The report inventory shows such nodes as unknown. If no node has host evidence the rule ends INSUFFICIENT_EVIDENCE.
- Freshness is checked on the newest row across nodes; a node whose host snapshot is older than the others is still evaluated on its latest data.
- Usage percent only; growth rate and time-to-full need history (Capacity Forecasting, Phase 3).
- Linux host evidence only.

**Verification**  
Unit tests: boundaries, threshold order, mount selection, independent nodes, missing data directory. Repository test: end-to-end run with two nodes (CRITICAL on node-1, thresholds stored) and INSUFFICIENT_EVIDENCE without host evidence. Lab: pending.

---

# PG_CONFIGURATION_HEALTH — Configuration Health

All three rules read the latest `PG_CONFIGURATION_SNAPSHOT` (`pg_settings`) of every node (freshness 86400 s) and produce one finding per node and setting. Only server-level values are visible; per-user, per-database and per-session values are not.

## PG-CONF-001 — Pending Restart

| | |
| --- | --- |
| Condition | `pending_restart = true` |
| Severity | WARNING |
| Details | Node, setting, running value, source |

**Known limitations**  
The new (not yet active) value is in `pg_file_settings`, which is not collected; the finding shows the running value.

## PG-CONF-002 — Unsafe Durability Settings

| | |
| --- | --- |
| Condition | `fsync = off` or `full_page_writes = off` — CRITICAL; `synchronous_commit = off` — WARNING |
| Severity | Per setting (rule has no default severity) |

**Design notes**  
fsync and full_page_writes off can corrupt the database after a crash. synchronous_commit off loses only the last commits and is a conscious choice in some systems; WARNING per the review decision of 2026-10-20. Accepted risks belong to the finding lifecycle (Phase 2).

## PG-CONF-004 — Autovacuum Disabled

| | |
| --- | --- |
| Condition | `autovacuum = off`, or `track_counts = off` (autovacuum cannot work without it) |
| Severity | CRITICAL |

**Known limitations**  
Per-table `autovacuum_enabled = false` is not visible yet (needs reloptions in PG-005).

**Verification (PG-CONF-001/002/004)**  
Unit tests; repository test runs the real configuration collector on a disposable PostgreSQL, the worker persistence and the assessment. Lab: pending.

---

# PG_CONNECTION_HEALTH — additional rule

## PG-CONN-002 — Connection Capacity

| | |
| --- | --- |
| Evidence | `PG_CONNECTION_ACTIVITY` (primary, 600 s); `PG_CONFIGURATION_SNAPSHOT` (86400 s) and `PG_INSTANCE_INVENTORY` (3600 s) to find the primary's limits; all required |
| Metric | client backends / (`max_connections` − `superuser_reserved_connections` − `reserved_connections`) in percent |
| Thresholds | WARNING ≥ 80 %, CRITICAL ≥ 90 % |
| Details | Connections in use, max_connections, reserved, usable, active / idle / idle in transaction |

**Known limitations**  
Replicas are not evaluated (connections are collected through the SYSTEM connection, which reaches the primary). Background workers and replication connections are not counted against the limit here.

# Batch of 2026-10-21 — MultiXact, WAL archiving, security (V038)

## PG-TRAN-004 — Database MultiXact Wraparound Risk (PG_TRANSACTION_HEALTH, topic MAINTENANCE)

| | |
| --- | --- |
| Evidence | `PG_TRANSACTION_WRAPAROUND` (`mxid_age` per database), required, 86400 s |
| Thresholds | WARNING ≥ 1.5 billion, CRITICAL ≥ 1.8 billion (unit MULTIXACT) |
| Subject | DATABASE |

Known limitations: relative to `autovacuum_multixact_freeze_max_age` not evaluated; MultiXact member space exhaustion is not visible in this evidence.

## PG-BKP-002 — WAL Archiving (PG_BACKUP_HEALTH, topic BACKUP)

| | |
| --- | --- |
| Evidence | `PG_CONFIGURATION_SNAPSHOT` (86400 s) and `PG_INSTANCE_INVENTORY` (3600 s), required |
| Condition | On the primary: `archive_mode = off` — WARNING (no point-in-time recovery; may be a conscious choice); `archive_mode` on / always with empty `archive_command` and `archive_library` — CRITICAL (WAL accumulates until the disk is full) |
| Subject | SETTING on the primary |

Known limitations: whether archiving succeeds is PG-BKP-001 (V041). Backups themselves are detected later by method (catalogue decision 4).

## PG-SEC-002 — MD5 Password Encryption / PG-SEC-003 — SSL Disabled (PG_SECURITY_HEALTH, topic SECURITY)

| | |
| --- | --- |
| Evidence | `PG_CONFIGURATION_SNAPSHOT`, required, 86400 s |
| Condition | `password_encryption = md5`; `ssl = off`; per node |
| Severity | WARNING |

Known limitations: roles that still have md5 hashes need `pg_authid` (superuser) and are not seen; `pg_hba.conf` rules (hostssl, md5, trust) are PG-SEC-005.

**Verification (V038)**  
Unit tests for every condition and boundary. Lab: pending.

---

# Batch of 2026-10-26 — archive failures, prepared transactions, failover (V041, PG015)

Two new collectors: `PG_WAL_STATUS` (NODE: `pg_stat_archiver`, `archive_mode`, the primary's current timeline from its WAL file name and the modification time of that timeline's history file from `pg_ls_waldir()`) and `PG_PREPARED_TRANSACTIONS` (SYSTEM: one status row, always present, plus one row per `pg_prepared_xacts` entry). Both work with `pg_monitor`.

An evaluator may now raise `InsufficientEvidence(source, code, message)`: the rule ends INSUFFICIENT_EVIDENCE with the reason `SOURCE: [code] message`, and the report explains the code in its language.

## PG-BKP-001 — WAL Archive Failures (PG_BACKUP_HEALTH, topic BACKUP)

| | |
| --- | --- |
| Evidence | `PG_WAL_STATUS`, required, 900 s |
| Condition | Per node that archives (primary with `archive_mode` on / always; replica only with always): `last_failed_time` newer than `last_archived_time` (or no success recorded) |
| Severity | CRITICAL |
| Subject | NODE; FINDING_ALT when no successful archive is recorded |
| Details | failed / archived counts, last failed and last archived WAL and time, statistics reset |

Known limitations: failures followed by a success are history, not a finding. "No success for a long time" is not judged; a quiet system may not switch WAL files for hours (needs WAL generation rate). Nodes with `archive_mode = off` are PG-BKP-002. Counters reset with `pg_stat_reset_shared('archiver')`.

## PG-TRAN-005 — Long Prepared Transaction (PG_TRANSACTION_HEALTH, topic TRANSACTIONS)

| | |
| --- | --- |
| Evidence | `PG_PREPARED_TRANSACTIONS`, required, 600 s |
| Metric | `captured_at − prepared` per prepared transaction |
| Thresholds | WARNING ≥ 5 min, CRITICAL ≥ 1 h |
| Subject | PREPARED_TRANSACTION (gid); details database, owner, transaction id |

A prepared transaction keeps its locks and holds back vacuum with no session attached, so PG-TRAN-003 cannot see it. The recommendation warns against rolling back without the transaction manager. `max_prepared_transactions = 0` simply means no findings.

## PG-HA-001 — Recent Failover (PG_REPLICATION_HEALTH, topic REPLICATION)

| | |
| --- | --- |
| Evidence | `PG_WAL_STATUS`, required, 900 s |
| Metric | time since the primary's current timeline began (`captured_at − timeline_started_at`, both from the primary's clock) |
| Condition | within parameter `recent_failover_window` (86 400 s) → WARNING |
| Insufficient evidence | no primary among the collected nodes (`no_primary`); timeline > 1 but its history file is not in `pg_wal` (`no_timeline_history`) |
| Subject | NODE (current primary) |

**Design notes**  
No history is needed, so a first health check can answer. Only the current timeline's history file is used: it is written by the primary's own promotion. Older history files are copied by `pg_basebackup` / `pg_rewind` with a new modification time (lab 2026-10-26: `00000044.history` showed the time a node was rebuilt), so they cannot date older failovers and failovers are not counted. Timeline 1 means the cluster was never promoted. The executive inventory shows the last failover (or "never") from this check's collection, whether or not the rule fires.

**Known limitations**  
Planned switchovers and unplanned failovers look the same. A whole cluster restored from a backup also starts a new timeline and is reported.

**Verification (V041)**  
Unit tests for every condition; repository test runs both real collectors on a disposable PostgreSQL, the worker persistence and the three assessments, including the insufficient-evidence path. Lab 2026-10-26 (hc37): clean state as expected; with `archive_command = /bin/false` PG-BKP-001 CRITICAL (no successful archive recorded, FINDING_ALT) and PG-BKP-002 healthy; a prepared transaction after 6 minutes PG-TRAN-005 WARNING; PG-HA-001 WARNING for the failover 3 hours earlier, a Patroni restart did not count as a failover.

---

# Batch of 2026-10-27 — indexes and security objects (V042, PG016)

New collectors: `PG_INDEX_USAGE` (scope NODE_DATABASE, ADR-0009: every database of every node; a DATABASE row per collected database with `pg_is_in_recovery()` and the statistics start, an INDEX row per user index with scans, size, validity, uniqueness, constraint and whether `CREATE INDEX CONCURRENTLY` is still running), `PG_SCHEMA_PRIVILEGES` (DATABASE: PUBLIC usage / create per user schema) and `PG_ROLES` (SYSTEM: role attributes, predefined `pg_*` roles left out, no password hashes). All work with `pg_monitor`.

## PG-IDX-001 — Unused Index (PG_INDEX_HEALTH, topic INDEXES)

| | |
| --- | --- |
| Evidence | `PG_INDEX_USAGE`, required, 86400 s; latest snapshot per node and database plus the list of nodes the system should have |
| Condition | scans summed over all nodes = 0; size ≥ `min_index_size` (10 MB); not backing a primary key, unique or exclusion constraint; valid and not being built; not owned by an extension (PG017) |
| Statistics age | shortest over the nodes (`pg_stat_database.stats_reset`, server start when never reset); always stated; under `min_statistics_age` (7 days) not judged; under `full_cycle` (365 days) the finding warns about periodic use (FINDING_ALT) |
| Missing node | a sum above 0 on the reachable nodes decides "used"; a sum of 0 with a node not collected for that database → INSUFFICIENT_EVIDENCE (`index_usage_incomplete`, names the node) |
| Severity | WARNING |
| Subject | INDEX (`database.schema.index`); observed value = size |

**Design notes** (Hasan, 2026-10-26/27)  
Scan counts are kept per server and are not replicated: an index serving reports on a replica shows 0 scans on the primary, and dropping it on the primary drops it everywhere. In the field an index used only by the year-end bank transfer was dropped as "unused" and that job failed; hence WARNING only, the statistics age in every finding and the periodic-use warning. The first recommended step is to check periodic use before dropping.

**Known limitations**  
When statistics were never reset, the server start time is used: conservative after a restart (the age looks shorter than it is). Statistics are lost after a crash. Duplicate and redundant indexes are PG-IDX-003.

## PG-IDX-002 — Invalid Index (PG_INDEX_HEALTH, topic INDEXES)

| | |
| --- | --- |
| Evidence | `PG_INDEX_USAGE`, required, 86400 s; rows of the current primary only |
| Condition | `indisvalid = false`, no `CREATE INDEX CONCURRENTLY` running for it, not owned by an extension |
| Severity | WARNING; unique index CRITICAL (uniqueness is not enforced, FINDING_ALT) |
| Insufficient evidence | no primary among the collected nodes (`no_primary`) |

Read from the primary only: an index still being built is invalid on the replicas too, and the build progress is visible only where it runs.

Indexes of extensions (the index or its table is an extension member in `pg_depend`) are left out of both rules: they are not the DBA's to drop or rebuild. Lab 2026-10-27: 13 of 14 first IDX-001 findings were TimescaleDB catalog indexes.

## PG-SEC-001 — Login Superuser (PG_SECURITY_HEALTH, topic SECURITY)

| | |
| --- | --- |
| Evidence | `PG_ROLES`, required, 86400 s |
| Condition | `rolsuper` and `rolcanlogin`, except the bootstrap superuser (OID 10, created by initdb, whatever its name) |
| Severity | WARNING, one finding per role |

A replication user needs only the REPLICATION attribute and a pg_rewind user a few function grants; neither needs superuser, so they are not excluded. A customer allow-list belongs to accepted risk (MVP Plan Phase 2). Known limitation: superusers without a password are not visible (`pg_authid`).

## PG-SEC-004 — PUBLIC Can Create in Schema (PG_SECURITY_HEALTH, topic SECURITY)

| | |
| --- | --- |
| Evidence | `PG_SCHEMA_PRIVILEGES`, required, 86400 s |
| Condition | PUBLIC has CREATE on a user schema (system and toast schemas excluded); a NULL ACL is the owner-only default |
| Severity | WARNING, one finding per database and schema |

Before PostgreSQL 15 every role could create in `public` by default, and upgraded databases keep it (CVE-2018-1058 search_path attack). Known limitation: `template1` is not collected (database fan-out skips templates), so a new database may inherit the grant unseen.

**Verification (V042)**  
Unit tests for every condition, including the field cases (used only on a replica, missing node with and without scans, short statistics). Repository test runs the three real collectors on a disposable PostgreSQL with an unused index, an invalid unique index left by a failed `CREATE UNIQUE INDEX CONCURRENTLY`, PUBLIC CREATE on `public`, an extension's own table and an extra login superuser. Lab 2026-10-27 (hc41): an index used only on a replica was not reported, its unused sibling was; an invalid unique index CRITICAL; an extra login superuser WARNING; PUBLIC CREATE found on `public` of all three lab databases (real finding).

---

# PG-CAP-002 — Sequence Exhaustion (PG_CAPACITY_HEALTH, topic STORAGE, V044, PG018)

| | |
| --- | --- |
| Evidence | `PG_SEQUENCE_CAPACITY` (DATABASE, primary; sequence values replicate), required, 86400 s |
| Metric | last value / limit; the limit is the bound the sequence moves towards (maximum, or minimum for a descending one), tightened by the type of the column it feeds (serial or identity): a bigint sequence feeding an integer column stops at 2,147,483,647 |
| Thresholds | WARNING ≥ 75 %, CRITICAL ≥ 90 %, judged unrounded |
| Not judged | cycling sequences (wrap on purpose), never-used sequences, sequences of extensions |
| Privilege | the value needs SELECT or USAGE on the sequence; `pg_monitor` is not enough. Unreadable sequences are never treated as healthy: with no finding the rule ends INSUFFICIENT_EVIDENCE (`sequence_privilege_missing`, names the grant) |
| Subject | SEQUENCE (`database.schema.sequence`); details column, types, last value, limit and what sets it |

Topic STORAGE is renamed "Storage and capacity" (TR "Depolama ve kapasite").

**Known limitations**  
Keys generated by the application (`max(id) + 1`) and foreign key columns of a smaller type than the key they reference are not seen. With partial privilege and at least one finding, the unreadable sequences are not mentioned.

**Verification (V044)**  
Unit tests for the column-type limit, boundaries, descending, cycling, unused and unreadable sequences. Repository test runs the real collector with a serial table at 93 % and an identity column, as superuser and as a `pg_monitor`-only role. Lab: pending.

---

# PG_MAINTENANCE_HEALTH — Maintenance Health (V039)

Both rules read the latest `PG_VACUUM_ANALYZE` snapshot per database (one row per table, freshness 86400 s) and produce one finding per table. Severity: ratio ≥ WARNING / CRITICAL threshold; below the ratio but count ≥ the large-table parameter → WARNING; below the minimum count the table is not judged. Ratios are judged unrounded and shown rounded. The report shows the worst 10 findings per rule and the rest under "show all".

## PG-MAINT-001 — Dead Tuple Pressure

| | |
| --- | --- |
| Metric | `n_dead_tup / (n_live_tup + n_dead_tup)` |
| Thresholds | WARNING ≥ 20 %, CRITICAL ≥ 40 % |
| Parameters | `min_dead_tuples` 10 000; `large_table_dead_tuples` 50 000 000 |

## PG-MAINT-002 — Stale Statistics

| | |
| --- | --- |
| Metric | `n_mod_since_analyze / n_live_tup` (empty tables judged by count only) |
| Thresholds | WARNING ≥ 20 %, CRITICAL ≥ 50 % |
| Parameters | `min_modifications` 10 000; `large_table_modifications` 50 000 000 |

**Design notes**  
Defaults sit just above PostgreSQL's autovacuum scale factors (vacuum 20 %, analyze 10 %), so a finding means autovacuum is behind. The large-table limit (Hasan, 2026-10-26) catches tables where 20 % is already hundreds of millions of rows.

**Known limitations**  
`n_live_tup` / `n_dead_tup` are estimates from the statistics system and reset with `pg_stat_reset`. Per-table autovacuum settings (reloptions) are not collected, so a table tuned on purpose is judged with the defaults. Bloat in bytes is PG-MAINT-004 (needs a collector).

**Verification**  
Unit tests for boundaries, the large-table path and parameters; repository test with snapshots of two databases. Lab: pending.

---

# Adding a Rule

Texts (V029, V030, V034, V040): every rule has NAME, HEALTHY, MEANING, CAUSES, IMPACT, RECOMMENDATION and FINDING in every Dictionary language. FINDING is the finding sentence with the same placeholders as `finding_template`; a rule with a second sentence shape sets `"_alt": true` in its template values and adds FINDING_ALT. MEANING is one statement of what is happening; CAUSES and RECOMMENDATION are short lists (one item per line starting with "- "), rendered as bullets, a topic and at least one impact category. A HEALTHY text states only what the rule checked and its limit, using `{warning}` / `{critical}` for thresholds so the text always matches the thresholds used. Contract tests enforce both.

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
| Long Resource-Retaining Aborted Transaction | Savepoint limitation above | Yes (`PG_ACTIVITY_SNAPSHOT`) |
| XID age relative to `autovacuum_freeze_max_age` | PG-TRAN-002 limitation | Yes (wraparound + configuration snapshots) |
| Filesystem capacity of tablespaces and a separate `pg_wal` | PG-CAP-001 limitation | Partly (needs tablespace paths) |
| Mixed PostgreSQL versions across nodes | Inventory review 2026-10-20 | Yes (`PG_INSTANCE_INVENTORY`) |
| Replica smaller than primary (CPU, memory) | Inventory review 2026-10-20 | Yes (`PG_HOST_SNAPSHOT`) |
