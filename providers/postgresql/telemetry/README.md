# PostgreSQL Telemetry

Collectors read PostgreSQL system catalogs and statistics views with a read-only role (`pg_monitor` is enough) and create nothing on the target. The installer registers every file in `collectors/` from its header (Key, Execution Scope, Execution Type); the worker stores the rows through the handler of the same key (`repository/worker/worker.py`, `COLLECTOR_HANDLERS`). Repository tables are created by the migrations in `repository/migrations/` (PG001–PG024).

| Key | Scope | Repository table(s) | Used by |
| --- | --- | --- | --- |
| PG_INSTANCE_INVENTORY | NODE | `instance_inventory` (current row per node) | Primary detection, report inventory |
| PG_CONFIGURATION_SNAPSHOT | NODE | `configuration_snapshot` | PG-CONF-*, PG-BKP-002, PG-SEC-002/003, PG-CONN-002, PG-CAP-001 |
| PG_HOST_SNAPSHOT (SSH) | NODE | `host_snapshot` (with `virtualization`, PG021), `storage_snapshot` (with `rotational` from lsblk ROTA, PG021) | PG-CAP-001, report inventory, storage type note |
| PG_WAL_STATUS | NODE | `wal_status_snapshot` | PG-BKP-001, PG-HA-001, report inventory |
| PG_CHECKPOINT_STATS | SYSTEM | `checkpoint_stats_snapshot` | PG-CONF-003 (`max_wal_size`), PG-PERF-003; `pg_stat_bgwriter` before 17, `pg_stat_checkpointer` from 17, chosen through `query_to_xml` |
| PG_INDEX_USAGE | NODE_DATABASE | `index_usage_snapshot` (with index definitions, PG022) | PG-IDX-001/002/003 |
| PG_DATABASE_INVENTORY | SYSTEM | `database_snapshot` | Report inventory |
| PG_DATABASE_STATS | SYSTEM | `database_stats_snapshot` (PG024): `pg_stat_database` counters per database | PG-PERF-002, PG-CAP-005 |
| PG_ACTIVITY_SNAPSHOT | SYSTEM | `activity_snapshot` | PG-TRAN-001/003/007 |
| PG_CONNECTION_ACTIVITY | SYSTEM | `connection_activity_snapshot` | PG-CONN-001/002 |
| PG_REPLICATION_STATUS | SYSTEM | `replication_status_snapshot`, `replica_status_snapshot` | PG-REP-003/004/006 |
| PG_REPLICATION_SLOTS | SYSTEM | `replication_slot_status_snapshot`, `replication_slot_snapshot` | PG-REP-001/002/005 |
| PG_ROLES | SYSTEM | `role_snapshot` | PG-SEC-001 |
| PG_PREPARED_TRANSACTIONS | SYSTEM | `prepared_transaction_status_snapshot`, `prepared_transaction_snapshot` | PG-TRAN-005 |
| PG_TRANSACTION_WRAPAROUND | DATABASE | `transaction_wraparound_snapshot` | PG-TRAN-002/004 |
| PG_VACUUM_ANALYZE | DATABASE | `vacuum_analyze_snapshot` (DATABASE row per database, PG023) | PG-MAINT-001/002/003 |
| PG_SEQUENCE_CAPACITY | DATABASE | `sequence_capacity_snapshot` | PG-CAP-002 |
| PG_SCHEMA_PRIVILEGES | DATABASE | `schema_privilege_snapshot` | PG-SEC-004 |
| PG_TABLE_STRUCTURE | DATABASE | `table_structure_snapshot` (PG022): foreign keys with index coverage, unlogged tables | PG-IDX-004, PG-BKP-003 |
| PG_EXTENSIONS | DATABASE | `extension_snapshot` (PG022): installed and package versions | PG-LIFE-004 |
| PG_TABLE_CAPACITY | DATABASE | `table_capacity_snapshot` | Context (not yet used by a rule) |

Scopes (ADR-0009): NODE runs on every server of a cluster, SYSTEM once through the system connection (the primary), DATABASE once per database, NODE_DATABASE once per database on every server. A collector that can legitimately find nothing returns a SYSTEM or DATABASE row anyway, so "none" is evidence (`PG_PREPARED_TRANSACTIONS`, `PG_INDEX_USAGE`, `PG_SCHEMA_PRIVILEGES`, `PG_TABLE_STRUCTURE`, `PG_EXTENSIONS`, `PG_VACUUM_ANALYZE`).

## Privileges

`pg_monitor` is enough for every collector, with one exception: the value of a sequence (`PG_SEQUENCE_CAPACITY`) needs SELECT or USAGE on it. SELECT on a sequence exposes only its counter, not table data. Without it PG-CAP-002 ends INSUFFICIENT_EVIDENCE and names the privilege. Recommended grant, per schema:

```sql
GRANT SELECT ON ALL SEQUENCES IN SCHEMA app TO keystone;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT ON SEQUENCES TO keystone;   -- sequences created later
```

`pg_read_all_data` (PostgreSQL 14+) also works but grants reading all table data.

Files ending in `.aql` (`query_stats_snapshot`, `replication_snapshot`) are drafts; the installer registers only `.sql` and `.sh`.

Rules and their evidence: `docs/KeyStone/06 - Engineering Intelligence/Rule Catalog.md`. Planned collectors: `docs/KeyStone/02 - Roadmap/Roadmap.md`.


## Offline evidence (ADR-0018)

The same collector files are wrapped into two read-only scripts by `python -m repository.offline.bundle --out <folder>` (node script: SYSTEM and NODE collectors; database script: DATABASE and NODE_DATABASE collectors). Collectors must therefore stay single SQL statements. The host collector prints a `CAPTURED_AT` section for offline use; `host_snapshot_windows.ps1` in `repository/offline` prints the same sections on Windows (`OS_FAMILY` WINDOWS, drive letters as devices and mount points).
