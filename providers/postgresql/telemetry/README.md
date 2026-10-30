# PostgreSQL Telemetry

Collectors read PostgreSQL system catalogs and statistics views with a read-only role (`pg_monitor` is enough) and create nothing on the target. The installer registers every file in `collectors/` from its header (Key, Execution Scope, Execution Type); the worker stores the rows through the handler of the same key (`repository/worker/worker.py`, `COLLECTOR_HANDLERS`). Repository tables are created by the migrations in `repository/migrations/` (PG001–PG018).

| Key | Scope | Repository table(s) | Used by |
| --- | --- | --- | --- |
| PG_INSTANCE_INVENTORY | NODE | `instance_inventory` (current row per node) | Primary detection, report inventory |
| PG_CONFIGURATION_SNAPSHOT | NODE | `configuration_snapshot` | PG-CONF-*, PG-BKP-002, PG-SEC-002/003, PG-CONN-002, PG-CAP-001 |
| PG_HOST_SNAPSHOT (SSH) | NODE | `host_snapshot`, `storage_snapshot` | PG-CAP-001, report inventory |
| PG_WAL_STATUS | NODE | `wal_status_snapshot` | PG-BKP-001, PG-HA-001, report inventory |
| PG_INDEX_USAGE | NODE_DATABASE | `index_usage_snapshot` | PG-IDX-001/002 |
| PG_DATABASE_INVENTORY | SYSTEM | `database_snapshot` | Report inventory |
| PG_ACTIVITY_SNAPSHOT | SYSTEM | `activity_snapshot` | PG-TRAN-001/003 |
| PG_CONNECTION_ACTIVITY | SYSTEM | `connection_activity_snapshot` | PG-CONN-001/002 |
| PG_REPLICATION_STATUS | SYSTEM | `replication_status_snapshot`, `replica_status_snapshot` | PG-REP-003/004/006 |
| PG_REPLICATION_SLOTS | SYSTEM | `replication_slot_snapshot` | PG-REP-001/002/005 |
| PG_ROLES | SYSTEM | `role_snapshot` | PG-SEC-001 |
| PG_PREPARED_TRANSACTIONS | SYSTEM | `prepared_transaction_status_snapshot`, `prepared_transaction_snapshot` | PG-TRAN-005 |
| PG_TRANSACTION_WRAPAROUND | DATABASE | `transaction_wraparound_snapshot` | PG-TRAN-002/004 |
| PG_VACUUM_ANALYZE | DATABASE | `vacuum_analyze_snapshot` | PG-MAINT-001/002 |
| PG_SEQUENCE_CAPACITY | DATABASE | `sequence_capacity_snapshot` | PG-CAP-002 |
| PG_SCHEMA_PRIVILEGES | DATABASE | `schema_privilege_snapshot` | PG-SEC-004 |
| PG_TABLE_CAPACITY | DATABASE | `table_capacity_snapshot` | Context (not yet used by a rule) |

Scopes (ADR-0009): NODE runs on every server of a cluster, SYSTEM once through the system connection (the primary), DATABASE once per database, NODE_DATABASE once per database on every server. A collector that can legitimately find nothing returns a SYSTEM or DATABASE row anyway, so "none" is evidence (`PG_PREPARED_TRANSACTIONS`, `PG_INDEX_USAGE`, `PG_SCHEMA_PRIVILEGES`).

## Privileges

`pg_monitor` is enough for every collector, with one exception: the value of a sequence (`PG_SEQUENCE_CAPACITY`) needs SELECT or USAGE on it. SELECT on a sequence exposes only its counter, not table data. Without it PG-CAP-002 ends INSUFFICIENT_EVIDENCE and names the privilege. Recommended grant, per schema:

```sql
GRANT SELECT ON ALL SEQUENCES IN SCHEMA app TO keystone;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT ON SEQUENCES TO keystone;   -- sequences created later
```

`pg_read_all_data` (PostgreSQL 14+) also works but grants reading all table data.

Files ending in `.aql` (`database_stats_snapshot`, `query_stats_snapshot`, `replication_snapshot`) are drafts; the installer registers only `.sql` and `.sh`.

Rules and their evidence: `docs/KeyStone/06 - Engineering Intelligence/Rule Catalog.md`. Planned collectors: `docs/KeyStone/02 - Roadmap/Roadmap.md`.
