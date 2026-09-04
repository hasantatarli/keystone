# PostgreSQL Collector Roadmap

This catalog tracks the planned PostgreSQL collection capabilities. Collector scope describes execution scope, not target topology.

| ID | Keystone Collector | Scope | Data Type | Finding Potential | Status |
| --- | --- | --- | --- | --- | --- |
| PG-001 | Instance Inventory | NODE | CURRENT | Low | **Done** |
| PG-002 | Configuration Snapshot | NODE | SNAPSHOT | High | **Done** |
| PG-003 | Database Inventory & Capacity | SYSTEM | SNAPSHOT | Medium | **Done** |
| PG-004 | Table & Index Capacity | DATABASE | SNAPSHOT | Medium | **Done** |
| PG-005 | Vacuum & Analyze Statistics | DATABASE | SNAPSHOT | Very High | **Next** |
| PG-006 | Transaction / Wraparound Health | SYSTEM / DATABASE | SNAPSHOT | Very High | Planned |
| PG-007 | Replication & Slot Health | SYSTEM / NODE | SNAPSHOT | Very High | Planned |
| PG-008 | Session & Connection Activity | SYSTEM / DATABASE | SNAPSHOT | High | Planned |
| PG-009 | Locking / Long Transactions | DATABASE | SNAPSHOT / EVENT | Very High | Planned |
| PG-010 | Index Inventory & Usage | DATABASE | SNAPSHOT | Very High | Planned |
| PG-011 | Index Quality | DATABASE | SNAPSHOT | Very High | Planned |
| PG-012 | pg_stat_statements Workload | DATABASE | SNAPSHOT / DELTA | Very High | Planned |
| PG-013 | Tablespace Capacity | NODE / SYSTEM | SNAPSHOT | High | Planned |
| PG-014 | Bloat / Fragmentation | DATABASE | SNAPSHOT | Very High | Planned |
| PG-015 | Extensions Inventory | DATABASE | SNAPSHOT | High | Planned |
| PG-016 | Roles & Security | SYSTEM / DATABASE | SNAPSHOT | Very High | Planned |
| PG-017 | SSL / HBA / Access Security | NODE | SNAPSHOT | Very High | Planned |
| PG-018 | Schema / Object Inventory | DATABASE | SNAPSHOT | Medium | Planned |
| PG-019 | Sequence Capacity | DATABASE | SNAPSHOT | Very High | Planned |
| PG-020 | Prepared Transactions | SYSTEM / DATABASE | SNAPSHOT | High | Planned |
| PG-021 | Partition Inventory | DATABASE | SNAPSHOT | Medium | Planned |
| PG-022 | FK / Constraint Health | DATABASE | SNAPSHOT | High | Planned |
| PG-023 | Function / Trigger Statistics | DATABASE | SNAPSHOT | Medium | Planned |
| PG-024 | Temp Objects / Temp Usage | DATABASE | SNAPSHOT | High | Planned |
| PG-025 | Large Objects Inventory | DATABASE | SNAPSHOT | Low | Planned |
| PG-026 | TOAST Mapping | DATABASE | SNAPSHOT | Low | Planned |
| PG-027 | Background Processes | NODE | SNAPSHOT | Medium | Planned |
| PG-028 | DB Load / Activity Profile | SYSTEM / DATABASE | SNAPSHOT / DELTA | Very High | Planned |
| PG-029 | Multixact Wraparound | SYSTEM / DATABASE | SNAPSHOT | Very High | Planned |
| PG-030 | Unlogged / Risky Objects | DATABASE | SNAPSHOT | High | Planned |
| PG-031 | Provider-specific Telemetry | SYSTEM / NODE | SNAPSHOT | Variable | Later |

## Current Development Focus

The collection foundation is established through PG-001 to PG-004. The next implementation target is **PG-005 — Vacuum & Analyze Statistics**.

Higher-level findings and recommendations will be developed on top of collected telemetry rather than embedded into individual collectors.