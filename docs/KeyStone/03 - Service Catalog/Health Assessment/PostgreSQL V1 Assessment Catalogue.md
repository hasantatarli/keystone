# PostgreSQL V1 Assessment Catalogue

**Status:** Draft — review decisions of 2026-10-20 below  
**Last Updated:** 2026-10-20

## Purpose

The missing link in the Capability Roadmap derivation chain:

**Capability Map → V1 Scope → Profiles → Assessment Catalogue → Findings → Evidence Requirements → Collector Gaps → Implementation**

Until now rules were added one at a time, backwards from the collectors that existed. This catalogue lists the checks a PostgreSQL health assessment must make to be useful to a small or medium company, and derives rules and collector work from them.

Sources combined:

- **Capability domains** (Keystone Capability Roadmap) — group the checks.
- **`awslabs/pg-collector`** — the minimum bar (MVP Plan): none of its sections may be left uncovered. Coverage map at the end.
- **PostgreSQL collector roadmap PG-001…PG-031** (Roadmap) — where the evidence comes from.
- **2026-09-21 evidence matrix and interpretation constraints** (Design History).
- **Lab and report reviews of 2026-10-19/20** — candidates noted in the Rule Catalog.

## Principles

- **A check is a judgement, not data.** Each row answers a question an experienced DBA asks and says when the answer is a finding. pg_collector shows data and leaves the judgement to the reader; Keystone makes the judgement and explains it.
- **Context is not a check.** Lists such as databases, extensions or table sizes are shown in the report (Context section below) and never produce findings by themselves.
- **No finding without sufficient context** (2026-09-21): a large table, a configuration value, a missing index, a null maintenance timestamp or a connection breakdown is not a problem on its own.
- **Missing evidence is never healthy.** A check without its evidence ends INSUFFICIENT_EVIDENCE and the report says so.
- **Thresholds live in the Dictionary**, texts in TR/EN, every check has a topic and impact categories (Rule Catalog → Adding a Rule).
- **Read-only, least privilege.** Checks must work with a `pg_monitor`-level role. Checks that need superuser-only views are marked and degrade to INSUFFICIENT_EVIDENCE.

## How to read the tables

| Column | Meaning |
| --- | --- |
| Key | Proposed rule key; existing rules in **bold** |
| Check | Short name |
| Finding when | Proposed condition and default thresholds |
| Evidence | Collector roadmap ID / collector key. **Ready** = collected today, **Gap** = collector work needed |
| pg_c | Covered pg_collector section |
| Prio | **P1** before the first real engagement · **P2** MVP if time allows · **P3** after MVP · **Done** implemented |

---

## 1. Health & Assessment — Configuration

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| **PG-CONF-001** | Pending restart | A setting was changed but needs a restart (`pending_restart`) — WARNING | Ready: PG-002 | DB parameters | Done |
| **PG-CONF-002** | Unsafe durability settings | `fsync = off` or `full_page_writes = off` — CRITICAL; `synchronous_commit = off` — WARNING (may be a conscious choice) | Ready: PG-002 | DB parameters | Done |
| PG-CONF-003 | Settings far from the recommendation for this server | Current value far outside the recommended range computed from the server's facts (memory, CPUs, storage, connections, workload); first: memory settings. Recommendations are shown for every covered setting, findings only for large deviations | Ready: PG-002 + host memory/CPU · Gap: storage type, workload type | Memory setting | P1 |
| **PG-CONF-004** | Autovacuum disabled | `autovacuum = off` — CRITICAL; per-table `autovacuum_enabled = false` on large tables — WARNING | Ready (global): PG-002 · Gap (per table): reloptions in PG-005 | Vacuum & Statistics | Done |
| PG-CONF-005 | Diagnostics disabled | No slow-query logging, `log_lock_waits = off`, `pg_stat_statements` not loaded — INFO, because RCA is not possible later | Ready: PG-002 | pg_stat_statements extension | P2 |
| PG-CONF-006 | No safety timeouts | `idle_in_transaction_session_timeout = 0` while PG-TRAN-001 findings exist — recommendation, not a stand-alone finding | Ready: PG-002 | — | P3 |

## 2. Sessions & Connections

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| **PG-CONN-001** | Aborted idle transaction connections | ≥ 1 session idle in an aborted transaction | Ready: PG-008 | active sessions monitor | Done |
| **PG-CONN-002** | Connection capacity | Client connections ≥ 80 % of `max_connections − superuser_reserved_connections` — WARNING, ≥ 90 % — CRITICAL | Ready: PG-008 + PG-002 | active sessions monitor | Done |
| PG-CONN-003 | Database connection limit | A database at ≥ 90 % of its own `datconnlimit` | Ready: PG-003 + PG-008 | List of databases | P3 |
| PG-CONN-004 | Many idle connections without pooling | Idle share high and `max_connections` large — INFO with explanation only (constraint: a breakdown alone is not proof) | Ready: PG-008 | — | P3 |

## 3. Transactions, Wraparound & Locking

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| **PG-TRAN-001** | Long idle transaction | Idle in transaction ≥ 5 / 15 min | Ready: PG-009 (activity) | active sessions monitor | Done |
| **PG-TRAN-003** | Long-running transaction | Transaction age ≥ 30 / 60 min | Ready: PG-009 (activity) | — | Done |
| **PG-TRAN-002** | XID wraparound risk | `age(datfrozenxid)` ≥ 1.5 / 1.8 billion | Ready: PG-006 | Transaction ID TXID | Done |
| **PG-TRAN-004** | MultiXact wraparound risk | `mxid_age` relative to limits | Ready: PG-006 | datminmxid | Done |
| **PG-TRAN-005** | Orphaned prepared transactions | A prepared transaction older than 5 min — WARNING, 1 h — CRITICAL (holds locks and xmin, survives restarts) | Ready: PG_PREPARED_TRANSACTIONS | Orphaned prepare transactions | Done |
| PG-TRAN-006 | XID age relative to `autovacuum_freeze_max_age` | Anti-wraparound vacuum overdue or repeatedly not finishing | Ready: PG-006 + PG-002 | Transaction ID TXID | P2 |
| PG-LOCK-001 | Blocking and lock waits | Sessions waiting on locks longer than N seconds; the blocking session named | Gap: PG-009 locking | — | P2 |
| PG-TRAN-007 | Long-running query | An active statement running longer than N minutes | Ready: PG-009 (activity) | active sessions monitor | P2 |

## 4. Maintenance — Vacuum, Analyze, Bloat

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| **PG-MAINT-001** | Dead tuple pressure | Dead tuples ≥ X % of live **and** ≥ N rows (two parameters; revisits the one-threshold model) | Ready: PG-005 | Vacuum & Statistics | Done |
| **PG-MAINT-002** | Stale statistics | Many modifications since the last analyze on an active table | Ready: PG-005 | Vacuum & Statistics | Done |
| PG-MAINT-003 | Table never vacuumed / analyzed | Active table with no vacuum or analyze since the statistics reset (constraint: a null timestamp alone is not a finding) | Ready: PG-005 | Vacuum & Statistics | P2 |
| PG-MAINT-004 | Table and index bloat | Estimated bloat ≥ X % and ≥ N MB | Gap: PG-014 | Fragmentation (Bloat) | P2 |

## 5. Indexes

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| PG-IDX-001 | Unused index | `idx_scan = 0`, statistics older than N days, size ≥ X MB, not unique / primary key / constraint | Gap: PG-010 | Unused Indexes, Index Access Profile | P1 |
| PG-IDX-002 | Invalid index | `indisvalid = false` (failed `CREATE INDEX CONCURRENTLY`) | Gap: PG-011 | invalid indexes | P1 |
| PG-IDX-003 | Duplicate / redundant index | Same columns in the same order, or a prefix of another index | Gap: PG-011 | — | P2 |
| PG-IDX-004 | Foreign key without index | FK columns not leading any index on a table of meaningful size | Gap: PG-022 | — | P2 |
| PG-IDX-005 | Heavy sequential scans | Large table read mostly by sequential scans | Gap: `seq_scan`, `seq_tup_read` (extend PG-005) | Tabel Access Profile | P2 |

## 6. Capacity Engineering

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| **PG-CAP-001** | Data disk usage | Data disk ≥ 80 / 90 % (as `df`) | Ready: host + PG-002 | — | Done |
| PG-CAP-002 | Integer key / sequence exhaustion | `int4` key or sequence ≥ 75 % — WARNING, ≥ 90 % — CRITICAL of its maximum | Gap: PG-019 | PK or FK using numeric or integer data type | P1 |
| PG-CAP-003 | Separate WAL disk and tablespaces | Like PG-CAP-001 for `pg_wal` on its own mount and tablespaces | Gap: PG-013 + tablespace paths | Tablespaces Info | P2 |
| PG-CAP-004 | Memory pressure | Swap in use on a database server above X % | Ready: host | — | P2 |
| PG-CAP-005 | Heavy temporary file use | Temp bytes per database high | Gap: PG-024 / database statistics | — | P2 |
| PG-CAP-006 | Growth and time to full | Disk or database growth rate; days until full | History of host / PG-003 (Phase 3) | Database size, Table Size | P3 |

## 7. HA / DR — Replication and Topology

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| **PG-REP-001** | Slot WAL retention pressure | `wal_status = extended` | Ready: PG-007 | Replication slot | Done |
| **PG-REP-002** | Slot WAL unavailable | `wal_status` unreserved / lost | Ready: PG-007 | Replication slot | Done |
| **PG-REP-003** | Replication lag | Replay lag ≥ X seconds or ≥ N MB behind | Ready: PG_REPLICATION_STATUS | — | Done |
| **PG-REP-004** | Replica missing or disconnected | Fewer streaming replicas than the NODE replicas Keystone knows | Ready: PG_REPLICATION_STATUS + target tree | — | Done |
| **PG-REP-005** | Inactive replication slot | `active = false` (retains WAL, holds xmin) | Ready: PG-007 | Replication slot | Done |
| **PG-REP-006** | Synchronous replication without a synchronous standby | `synchronous_standby_names` set but no standby in `sync` state — CRITICAL, writes can hang | Ready: PG-002 + PG_REPLICATION_STATUS | — | Done |
| **PG-HA-001** | Recent failover | The primary's current timeline began within the last 24 h (history file time; no history needed) — WARNING | Ready: PG_WAL_STATUS | — | Done |
| PG-HA-002 | Recently restarted node | `postmaster_start_time` within the last 24 h — INFO, context for other findings | Ready: PG-001 | DB_START_DATE, UP_TIME | P2 |
| PG-HA-003 | Replica smaller than primary | Replica with fewer CPUs or < 90 % of the primary's memory | Ready: host | — | P2 |
| PG-HA-004 | Mixed versions across nodes | Different PostgreSQL minor versions in one cluster | Ready: PG-001 | — | P2 |

## 8. Backup & Recovery

WAL archiving settings and archiver statistics are collected (PG_CONFIGURATION_SNAPSHOT, PG_WAL_STATUS); backups themselves are not yet. This is the area with the highest real-world risk.

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| **PG-BKP-001** | WAL archiving failing | `pg_stat_archiver`: last failure after last success — CRITICAL | Ready: PG_WAL_STATUS | — | Done |
| **PG-BKP-002** | No point-in-time recovery possible | `archive_mode = off` on a primary — WARNING with explanation | Ready: PG-002 | — | Done |
| PG-BKP-003 | Unlogged tables | Unlogged tables exist: lost after a crash, not replicated — WARNING with the table list | Gap: PG-030 | Unlogged Tables | P2 |
| PG-BKP-004 | Last successful backup age | No successful backup within N hours (pgBackRest, Barman, pg_dump logs) | Gap: backup tool integration over SSH | — | P3 |

## 9. Security Engineering

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| PG-SEC-001 | Too many superusers | Login roles with superuser beyond the expected administrators | Gap: PG-016 | Users & Roles Info | P1 |
| **PG-SEC-002** | Weak password hashing | `password_encryption = md5` — WARNING (md5 is deprecated); roles still with md5 hashes need superuser | Ready (setting): PG-002 | Users & Roles Info | Done |
| **PG-SEC-003** | Connections without encryption | `ssl = off` — WARNING | Ready: PG-002 | — | Done |
| PG-SEC-004 | Anyone can create in `public` | `CREATE` on schema `public` granted to PUBLIC (default before PostgreSQL 15) | Gap: PG-018 / PG-016 | public Schema | P1 |
| PG-SEC-005 | Trust or password authentication | `trust` or plain `password` rules in `pg_hba` | Gap: PG-017 (`pg_hba_file_rules` needs superuser by default) | — | P2 |
| PG-SEC-006 | Broad default privileges | Default privileges granting write to PUBLIC or wide roles | Gap: PG-016 | Default access privileges, Access privileges | P3 |
| PG-SEC-007 | No audit logging | `pgaudit` not installed where compliance requires it — INFO | Gap: PG-015 | pgaudit extension | P3 |

## 10. Upgrade & Lifecycle

Needs a **release reference table** in the Dictionary (versions, release dates, end of support), updated by migration after each quarterly PostgreSQL release and for OS releases.

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| PG-LIFE-001 | Minor version behind | Behind the current minor of its major — WARNING; missed a release with a security fix — CRITICAL | Ready: PG-001 + reference table | DB_Version | P3 |
| PG-LIFE-002 | Major version support | Support ended — CRITICAL; ends within 12 months — WARNING (PostgreSQL 14: 2026-11-12) | Ready: PG-001 + reference table | DB_Version | P3 |
| PG-LIFE-003 | Operating system support | OS release past its standard support (for example CentOS 7, Ubuntu 18.04) | Ready: host + reference table | — | P2 |
| PG-LIFE-004 | Extensions with available updates | `installed_version < default_version` | Gap: PG-015 | Extensions | P2 |

## 11. Performance Engineering (health-check depth)

A health check shows performance indicators; it does not replace a Performance Investigation profile.

| Key | Check | Finding when | Evidence | pg_c | Prio |
| --- | --- | --- | --- | --- | --- |
| PG-PERF-001 | Most expensive queries | Top queries by total time shown as context; finding when one statement dominates (≥ X % of total time) | Gap: PG-012 (needs `pg_stat_statements`) | pg_stat_statements extension | P2 |
| PG-PERF-002 | Low cache hit ratio | Shared buffer hit ratio below X % on an active database | Gap: database statistics | — | P2 |
| PG-PERF-003 | Checkpoints too frequent | Requested checkpoints dominate timed ones (`max_wal_size` too small) | Gap: checkpointer / bgwriter statistics | — | P2 |
| PG-PERF-004 | Deadlocks and rollbacks | Deadlocks or rollback ratio increased between checks | Gap: database statistics with history | — | P3 |

---

## Context shown in the report (not checks)

| Context | Evidence | pg_c |
| --- | --- | --- |
| Servers: role, version, uptime, OS, CPU, memory, data disk | PG-001, host, PG-002 | DB INFO |
| Platform (physical / VM / cloud, hypervisor) | Gap: host snapshot extension | — |
| Databases: owner, encoding, collation, size, connection limit | PG-003 | List of databases, Database size |
| Largest tables and indexes, TOAST share | PG-004 | Table Size, Index Size, Toast Tables Mapping |
| Installed extensions | Gap: PG-015 | Extensions |
| Schemas and object counts | Gap: PG-018 | schema Info |
| Tablespaces | Gap: PG-013 | Tablespaces Info |
| Roles and memberships | Gap: PG-016 | Users & Roles Info |
| Non-default configuration | PG-002 | DB parameters |

---

## Summary

| | Done | P1 | P2 | P3 |
| --- | --- | --- | --- | --- |
| Checks | 7 | 25 | 22 | 8 |
| of which evidence ready | 7 | 17 | 9 | 3 |

With the 17 ready P1 checks Keystone reaches 24 checks without new collectors. Collectors needed for the remaining P1 checks, in proposed order:

1. **Release reference table** (Dictionary, not a collector) — PG-LIFE-001/002.
2. ~~**Archiver statistics** (new) — PG-BKP-001.~~ Done: PG_WAL_STATUS (V041).
3. **PG-010 / PG-011 Index usage and quality** — PG-IDX-001/002.
4. **PG-019 Sequence / integer key capacity** — PG-CAP-002.
5. ~~**PG-020 Prepared transactions** — PG-TRAN-005.~~ Done: PG_PREPARED_TRANSACTIONS (V041).
6. **PG-016 Roles**, **PG-018 schema privileges** — PG-SEC-001/004.
7. ~~**Timeline ID** in PG-001 — PG-HA-001.~~ Done: PG_WAL_STATUS (V041).

## pg_collector coverage

| pg_collector section | Covered by |
| --- | --- |
| DB INFO (version, start, uptime) | Context; PG-LIFE-001/002, PG-HA-002 |
| List of databases, datfrozenxid, datminmxid | Context; PG-TRAN-002, PG-TRAN-004, PG-CONN-003 |
| Database size | Context; PG-CAP-006 |
| DB parameters | PG-CONF-001/002/005 |
| Transaction ID TXID | PG-TRAN-002, PG-TRAN-006 |
| Table Size, Index Size | Context |
| Vacuum & Statistics | PG-MAINT-001/002/003, PG-CONF-004 |
| Extensions | Context; PG-LIFE-004 |
| Memory setting | PG-CONF-003 |
| pg_stat_statements extension | PG-PERF-001, PG-CONF-005 |
| Users & Roles Info | PG-SEC-001/002 |
| schema Info | Context |
| Tablespaces Info | Context; PG-CAP-003 |
| Tabel Access Profile | PG-IDX-005 |
| Unused Indexes | PG-IDX-001 |
| Index Access Profile | PG-IDX-001 |
| Fragmentation (Bloat) | PG-MAINT-004 |
| Toast Tables Mapping | Context |
| Replication slot | PG-REP-001/002/005 |
| active sessions monitor | PG-TRAN-001/007, PG-CONN-001/002 |
| Orphaned prepare transactions | PG-TRAN-005 |
| PK or FK using numeric or integer data type | PG-CAP-002 |
| public Schema | PG-SEC-004 |
| invalid indexes | PG-IDX-002 |
| Default access privileges, Access privileges | PG-SEC-006 |
| pgaudit extension | PG-SEC-007 |
| Unlogged Tables | PG-BKP-003 |

Beyond pg_collector: host and disk capacity, replication lag and topology, failover detection, WAL archiving, version and OS lifecycle, synchronous replication safety.

## Review decisions (2026-10-20)

1. **Order:** P1 first, then P2, then P3.
2. **Configuration becomes a recommendation capability, not only checks.** Most customers struggle with "which values should I set for my server?". Keystone computes recommended values from the server's facts (memory, CPUs, storage type, connections, version, workload) using documented best practice, shows current vs recommended with the reason, and raises findings only for large deviations. Design in a separate decision record before implementation.
   - **Scope:** recommendations for the 15–20 settings that matter most (memory, cache, WAL/checkpoint, I/O, parallelism, autovacuum, connections), not for all ~350. Every other setting changed from its default is listed so the engineer sees what was customised; it is context, not a finding, unless the setting is on a curated list of risky changes (for example `fsync`, `full_page_writes`, `autovacuum`), which have their own checks.
3. **Security:** the essential checks first (PG-SEC-001…004), details later.
4. **Backup:** PostgreSQL has no backup catalogue like SQL Server's `msdb`. Keystone detects the method in use and reports backups through that method. First signal without SSH: `archive_command` (pgBackRest `archive-push`, Barman `barman-wal-archive`, WAL-G `wal-push`, pg_probackup); then the tool's own status over SSH (`pgbackrest info --output=json` and equivalents) and `pg_dump` jobs in cron. Barman usually runs on a separate backup server; Keystone does not connect to it. The backup check then ends INSUFFICIENT_EVIDENCE — never healthy — with the reason "Backups are managed by Barman on a separate server; verify them there."
5. **Conscious choices** (`synchronous_commit = off`, `archive_mode = off` and similar) are WARNING by default. A customer's explicit acceptance ("accepted risk" with a reason) belongs to the finding lifecycle (MVP Plan Phase 2).

6. **Version checks deferred** (2026-10-21, Hasan): PG-LIFE-001/002 need current release data. Many customer servers have no internet access, and a manually maintained list creates recurring work. Moved to P3; revisit with a release table shipped with Keystone updates.

7. **Group 1 of the collector P1s** (2026-10-26, Hasan): PG-BKP-001 is CRITICAL only while the last failure is newer than the last success; "no success for a long time" is not judged. PG-TRAN-005 uses 5 / 60 minutes. PG-HA-001 dates the last failover from the current timeline's history file (works on a first check); a failover within 24 h is a WARNING.

## Open questions for review

1. ~~Priorities~~ — decided: P1 → P3.
2. **Default thresholds** — especially PG-MAINT-001, PG-IDX-001, PG-REP-003 and PG-CONF-003, where experience matters more than documentation.
3. **Superuser-only evidence** (`pg_hba_file_rules`, password hashes in `pg_authid`): accept as optional, or only in a separate security profile?
4. ~~Backup tools~~ — decided: detect the method in use (see decisions).
5. ~~Severity of conscious choices~~ — decided: WARNING.
