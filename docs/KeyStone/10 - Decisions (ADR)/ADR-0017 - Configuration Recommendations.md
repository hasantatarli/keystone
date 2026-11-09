# ADR-0017 — Configuration Recommendations

**Status:** Approved — implemented 2026-11-09 (steps 1–4, 3b-1, 3b-2a; 3b-2b in the backlog)  
**Date:** 2026-10-29

ADR-0016 is reserved for the customer overview (DEVELOPMENT_STATUS).

## Context

Most customers struggle with "which values should I set for this server?" (Assessment Catalogue, review decision 2). Keystone already flags unsafe settings (PG-CONF-001/002/004, PG-BKP-002, PG-SEC-002/003), but does not say what a setting should be. PG-CONF-003 turns configuration into a recommendation capability: Keystone computes recommended values from the server's facts with documented best practice, shows current against recommended with the reason, and raises findings only for large deviations. Every other setting changed from its default is listed as context, not as a finding.

## Decisions so far (Hasan, 2026-10-29)

### Server profile on the target

Facts Keystone cannot collect are recorded when the target is registered:

| Field | Values | Default when not given |
| --- | --- | --- |
| Workload type | OLTP / reporting (OLAP) / mixed | OLTP |
| Dedicated to PostgreSQL | yes / no | yes |
| Storage type | SSD / HDD | SSD |

The fields are optional. Keystone keeps "not given" apart from a chosen value: when a default is used, the report says so ("workload not specified; OLTP assumed"), because "dedicated" makes memory recommendations larger and is wrong if an application shares the server. The storage type collected over SSH (`/sys/block/*/queue/rotational`) is not trusted on its own (virtual disks often report rotational); it only raises a note when it contradicts the recorded value.

### Which server the recommendation is for

- **Workload** (connections, query profile) is read from the primary: the work happens there.
- **Hardware limits** come from the weakest node of the cluster. Settings are cluster-wide under Patroni and a replica becomes primary after a failover, so a value right for a 64 GB primary must still be safe on a 32 GB replica. The report states it: "Recommendations are calculated for the smallest server of the cluster (postgre-3: 2 CPU, 8 GB)."
- Settings that must not be lower on a standby than on the primary (`max_connections`, `max_worker_processes`, `max_prepared_transactions`, `max_locks_per_transaction`, `max_wal_senders`) are recommended once for all nodes.
- Node-specific values (for example a larger `work_mem` on a reporting replica) are out of scope for the first version.

### Which settings: only general best practice (Hasan, 2026-11-02)

Keystone recommends a value only where the PostgreSQL documentation recommends one or the practice is widely accepted (for example PGTune's calculations, `random_page_cost` 1.1 on SSD). Where the guidance is "keep the default and tune to your needs", the value would be Keystone's own experience presented as best practice; such settings are left out. They belong to the later intelligence layer, which can examine the system and ask the user (see "Later: intelligence layer").

### Settings covered (first version, 18)

C = CPUs and M = memory of the smallest node; M is halved when the server is not dedicated (`non_dedicated_memory_share` 0.5). Ranges are multiples of the recommended value (`range_low`/`range_high`) or plain values (`accept_min`/`accept_max`).

| Group | Setting | Recommended | Acceptable | Source |
| --- | --- | --- | --- | --- |
| Memory | `shared_buffers` | 25 % of M, at least 128 MB | 0.6–1.6× (15–40 %) | documentation |
| | `effective_cache_size` | 75 % of M | 0.67–1.2× | documentation |
| | `work_mem` | (M − shared_buffers) / (max_connections × k); k OLTP 4, mixed 2, OLAP 1; at least 4 MB, at most 64 MB / 256 MB / 1 GB | 0.25–4× | PGTune |
| | `maintenance_work_mem` | M / 16, 64 MB – 2 GB | 0.5–2× | PGTune |
| | `huge_pages` | `try` | `try`, `on` | documentation |
| WAL / checkpoint | `max_wal_size` | OLTP 4 GB, mixed 8 GB, OLAP 16 GB; at most 10 % of the data disk | 0.5–4× | PGTune |
| | `min_wal_size` | `max_wal_size` / 4 | 0.25–4× | PGTune |
| | `checkpoint_completion_target` | 0.9 | 0.8–0.95 | documentation (default since 14) |
| | `checkpoint_timeout` | 15 min | 10–30 min | widely used |
| | `wal_buffers` | 16 MB | 0.5–4× | documentation (automatic value) |
| Storage | `random_page_cost` | SSD 1.1, HDD 4.0 | SSD 1.0–2.0, HDD 2.0–4.0 | widely used |
| | `effective_io_concurrency` (15–17) | SSD 200, HDD 2 | 0.5–2× | widely used |
| Parallelism (only with C ≥ 4) | `max_worker_processes` | at least 8 and C | lower bound only (extensions and replication use it) | PGTune |
| | `max_parallel_workers` | C | 0.5–2× | PGTune |
| | `max_parallel_workers_per_gather` | C / 2 rounded up, at most 4 | 0.5–2× | PGTune |
| | `max_parallel_maintenance_workers` | C / 2 rounded up, at most 4 | 0.5–2× | PGTune |
| Observability | `log_min_duration_statement` | 1 s | 250 ms – 10 s | widely used |
| | `track_io_timing` | `on` (after `pg_test_timing`) | `on` | widely used |

`max_connections` is an input (the application's need), not a recommendation. Left out under the criterion above: `autovacuum_max_workers` and `autovacuum_vacuum_cost_limit` (no agreed numbers; autovacuum is judged by its results in PG-MAINT-001/002 and the wraparound rules), and the version-specific settings first planned (`vacuum_buffer_usage_limit`, `io_combine_limit`, `io_method`, `io_workers`, `autovacuum_worker_slots`). PostgreSQL 18 changed `effective_io_concurrency` (default 16 with asynchronous I/O) and no recommendation exists for it, so it is recommended on 15–17 only.

Every recommendation shows its reason and calculation, for example "shared_buffers: 25 % of memory; 16 GB × 0.25 = 4 GB".

Without host evidence (no SSH) memory and CPU are unknown: those settings are not assessed and the report says why.

### When a deviation is a finding

A recommendation is a value and an acceptable range around it (for example `shared_buffers` 25 % of memory, acceptable 15–40 %); several values can be right, and a conscious choice by an experienced DBA must not be flagged.

| Current value | Result |
| --- | --- |
| Inside the acceptable range | No finding; stored as FITS |
| Outside the range | INFO finding (PG-CONF-003) with the recommendation and its reason |
| Endangers the server | CRITICAL, from rules on combinations of settings, not single values: first, memory commitment (PG-CONF-007: `shared_buffers` + `max_connections` × `work_mem` above physical memory, risk of the OOM killer) |

A setting outside its range is a recommendation, not a problem (Hasan, 2026-11-02; first planned as WARNING). Executives need the risk, not the values: only CRITICAL configuration risk reaches the executive cards. Recommendations are a DBA's tool; their main place will be the management screens, and until those exist, the technical part of the report.

### Where the formulas live

Logic in code, numbers in the Dictionary, as for rules:

- **Code:** one calculation function per setting (for example `work_mem` from memory left after `shared_buffers`, connections and a factor; less memory when the server is not dedicated), unit-tested directly. No formula language (the rule DSL stays rejected).
- **Dictionary (new table, filled by migrations):** the tunable numbers per setting and workload type: factors, acceptable range bounds, lower and upper limits (for example `maintenance_work_mem` at most 2 GB). Tuning for a customer or sector changes data, not code.
- **Per health check:** the result of every recommendation is stored: setting, current value, recommended value, acceptable range, status and the Dictionary numbers used. The inputs (memory, CPUs, settings, profile) are not copied: they are already in the collected snapshots and the check's `target_profile`. The same raw data gives different results under different Dictionary numbers, so the result is what the customer was told and stays correct after the Dictionary changes, like `thresholds_used` (Hasan, 2026-11-02).

### Report layout (Hasan, 2026-11-02: keep the report short)

A long report is not read. Limits:

- **Executive:** no card for recommendations; at most one line in the configuration area ("3 settings differ from the values recommended for this server; details in the technical part"). The only exception is a CRITICAL combination (memory commitment), which is a problem card like any other risk.
- **Technical**, collapsible: what needs action is open (settings outside their range and settings not assessed, each with its reason, calculation and commands, `ALTER SYSTEM SET` and `patronictl edit-config --pg`, restart-requiring ones marked; Keystone writes them, never runs them); the settings that fit are one line with their count, the list closed; the calculation inputs (smallest server, workload, storage, dedicated, assumed defaults marked).
- **Not in the report:** other settings changed from their default. They are kept with every configuration snapshot for the management screens and the intelligence layer.

### Versions

Recommendations follow the server's PostgreSQL version, not a fixed list: every setting in the Dictionary has the version range it exists in (first version, and a last version for removed or renamed settings), and the numbers can differ per version. A setting the server's version does not have is never recommended; settings a version adds are recommended for that version. The version is read from the primary; mixed versions across nodes are their own finding (PG-HA-004).

The first version covers PostgreSQL 15–18; the only version-bound setting is `effective_io_concurrency` (15–17).

### Recomputed on every check, runnable on its own (Hasan, 2026-11-02)

Servers change: memory grows, CPUs and disks change. Recommendations are never fixed: every health check computes them from that check's facts. Configuration tuning is its own assessment (`PG_CONFIGURATION_TUNING`), so it can be run alone with `health_check --assessment PG_CONFIGURATION_TUNING`, and on a schedule like the other assessments. Because each check's facts are kept, the report can say when the hardware changed since the previous check ("memory 8 GB → 16 GB; recommendations recalculated"); not built yet (backlog, 2026-11-09).

### Later: intelligence layer

The configuration collector keeps every `pg_settings` row (about 350, with defaults and sources), not only the 18 above, together with host facts, the profile and Keystone's results. A later intelligence layer can work on this data: explain the results, and suggest values for settings Keystone does not check, asking the user where experience rather than best practice decides.

## Implementation order

1. Server profile on the target (workload type, dedicated, storage type; "not given" kept apart). Done 2026-11-02 (V046): `workload_type`, `dedicated`, `storage_type` on `keystone.target`, NULL for not given; each health check stores the profile it used with the assumed fields marked (`health_check.target_profile`); the technical report shows it. Reading `rotational` over SSH moves to step 3 with the calculations.
2. Dictionary table of settings: version range, factors and ranges per workload, limits. Done 2026-11-02 (V047): `config_setting` (group, value type, version range, order), `config_setting_text` (reason per language), `config_parameter` (numbers; the most specific row by workload, storage type and version wins).
3. a) Done 2026-11-02 (V048): calculation functions with unit tests, `PG_CONFIGURATION_TUNING` with PG-CONF-003 (INFO) and PG-CONF-007 (CRITICAL), results in `keystone.config_recommendation`. b-1) Done 2026-11-02 (V050, PG020): checkpoint evidence; collector `PG_CHECKPOINT_STATS` reads `pg_stat_bgwriter` (15–16) or `pg_stat_checkpointer` (17+) through `query_to_xml` in one script; optional evidence is now collected by the health check too (the rule works without it). b-2a) Done 2026-11-06 (PG021): storage type as a note; the host collector adds `lsblk` ROTA per device and `systemd-detect-virt --vm`; the report notes a data disk reporting another type than the profile, with a caveat on virtual machines (virtio and VMware disks report rotating on SSD, seen on the KVM build container). The profile stays the input. b-2b) Hardware change since the previous check: moved to the backlog on 2026-11-09 (recommendations are already recomputed from current hardware on every check). b) Checkpoint evidence (`pg_stat_bgwriter` / `pg_stat_checkpointer`: requested checkpoints above 20 % → `max_wal_size` doubled, WARNING); storage type over SSH as a note; hardware change since the previous check.
4. Report: area line, technical inputs, table of settings needing action, commands (see Report layout). Done 2026-11-02 (V049): `restart_required` (`pg_settings.context = postmaster`) and `assumptions` (profile fields the value rests on that were not given) stored with each result; executive line in the configuration area, settings not assessed added to the card of the missing data; technical section "Configuration recommendations" replaces the PG-CONF-003 finding card: inputs (smallest server), table of settings needing action with reason, calculation, assumption and node notes, `ALTER SYSTEM` and `patronictl edit-config` commands with the restart list, the settings that fit closed.

Each step is its own pull request and is reviewed in the lab.


## Addendum (2026-11-09, external review): safe commands

The commands were only checked as text. Changes (V052, reliability package step B):

- **Management type in the server profile** (`target.cluster_manager`: PATRONI, NONE, NULL not given). With Patroni only `patronictl edit-config` is written (ALTER SYSTEM would make the node drift from the DCS); without it only `ALTER SYSTEM`. Not given: both sets, every line a comment, with how to set the profile; Patroni sessions seen in `pg_stat_activity` are mentioned as a hint only, never used to choose (review: `application_name` is reported by the client and not always present).
- **Reload and restart apart.** `ALTER SYSTEM` settings that take effect with a reload end with `SELECT pg_reload_conf();`; settings that need a restart are a block of their own, without the reload. With Patroni: `patronictl restart --pending` after the edit when a restart setting is applied.
- **Assumed values are comments.** A recommendation resting on a profile field that was not given is written as a comment with the assumption, in both command sets, so a block copied as it is never applies a guess.
- **Windows.** PostgreSQL rejects `effective_io_concurrency` above 0 on Windows (no `posix_fadvise`): NOT_APPLICABLE there. Windows is recognised from `dynamic_shared_memory_type = windows` or a drive-letter data directory.
- **Applied in tests.** The `ALTER SYSTEM` blocks are run on a disposable PostgreSQL, reloaded and restarted, and `pg_settings` is compared with the recommendation. The `patronictl` commands are applied on the lab Patroni cluster during the lab check.
- **Lab findings on Patroni 4.1 (2026-11-09).** `patronictl restart` needs the cluster name: taken from PostgreSQL's `cluster_name` (Patroni's scope unless changed), else `<cluster>`. `patronictl edit-config` shows its diff with `less`; without it the command fails (install `less` or use `--quiet`). A setting in a node's local Patroni configuration (`postgresql.parameters` in its YAML) overrides the DCS: in the lab `shared_buffers: 256MB` in `config.yml` kept the DCS value of 492MB from taking effect, with no pending restart. Keystone cannot read that file over SQL; the report tells the DBA to check `SHOW` on every server after applying and to remove local overrides.
