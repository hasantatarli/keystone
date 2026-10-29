# ADR-0017 — Configuration Recommendations

**Status:** Draft (decisions being made)  
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

### Settings covered (first version, 20)

| Group | Settings | Based on |
| --- | --- | --- |
| Memory | `shared_buffers`, `effective_cache_size`, `work_mem`, `maintenance_work_mem`, `huge_pages` | memory, connections, workload, dedicated |
| WAL / checkpoint | `max_wal_size`, `min_wal_size`, `checkpoint_completion_target`, `checkpoint_timeout`, `wal_buffers` | workload, write volume |
| Storage | `random_page_cost`, `effective_io_concurrency` | storage type |
| Parallelism | `max_worker_processes`, `max_parallel_workers`, `max_parallel_workers_per_gather`, `max_parallel_maintenance_workers` | CPUs, workload |
| Autovacuum | `autovacuum_max_workers`, `autovacuum_vacuum_cost_limit` | CPUs, number and size of tables |
| Observability | `log_min_duration_statement`, `track_io_timing` | fixed good practice |

Sources: the PostgreSQL documentation and widely used rules (the logic of PGTune, EDB and Crunchy Data guidance). Every recommendation shows its reason and calculation, for example "shared_buffers: 25 % of memory; 16 GB × 0.25 = 4 GB".

Without host evidence (no SSH) memory and CPU are unknown: those settings are not assessed and the report says why.

### When a deviation is a finding

A recommendation is a value and an acceptable range around it (for example `shared_buffers` 25 % of memory, acceptable 15–40 %); several values can be right, and a conscious choice by an experienced DBA must not be flagged.

| Current value | Result |
| --- | --- |
| Inside the acceptable range | No finding; the table shows "fits" with the recommended value as information |
| Outside the range | WARNING with the recommendation and its reason |
| Endangers the server | CRITICAL, from rules on combinations of settings, not single values: first, memory commitment (`shared_buffers` + `max_connections` × `work_mem` above memory: risk of the OOM killer) |

The range of every setting is written down with its reason.

### Where the formulas live

Logic in code, numbers in the Dictionary, as for rules:

- **Code:** one calculation function per setting (for example `work_mem` from memory left after `shared_buffers`, connections and a factor; less memory when the server is not dedicated), unit-tested directly. No formula language (the rule DSL stays rejected).
- **Dictionary (new table, filled by migrations):** the tunable numbers per setting and workload type: factors, acceptable range bounds, lower and upper limits (for example `maintenance_work_mem` at most 2 GB). Tuning for a customer or sector changes data, not code.
- **Per health check:** every recommendation is stored with the setting, current value, recommended value, range, reason and the inputs used (memory, CPUs, workload, whether a default was assumed). Reports are built from it and stay correct after the Dictionary changes, like `thresholds_used`.

### Report layout (to be reviewed on the first real report)

- **Executive:** one main-problem card "Configuration deviates from the recommendations (N settings)", closed by default, the most important settings in plain words when opened; the configuration area says how many of the settings fit, deviate or endanger the server.
- **Technical**, collapsible: the calculation inputs first (smallest server used, workload, storage, dedicated; every assumed default marked); the recommendation table by group (setting, current, recommended, acceptable range, status, reason with the calculation); commands for the settings outside their range, both `ALTER SYSTEM SET` and `patronictl edit-config --pg`, restart-requiring ones marked (Keystone writes them, never runs them); other settings changed from their default as context (setting, value, default, source).

## Open questions

1. Version differences (settings added or renamed across PostgreSQL 15–18).
