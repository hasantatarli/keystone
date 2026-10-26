# PostgreSQL Collector Roadmap

This catalog tracks the planned PostgreSQL collection capabilities. Collector scope describes execution scope, not target topology.

| ID | Keystone Collector | Scope | Data Type | Finding Potential | Status |
| --- | --- | --- | --- | --- | --- |
| PG-001 | Instance Inventory | NODE | CURRENT | Low | **Done** |
| PG-002 | Configuration Snapshot | NODE | SNAPSHOT | High | **Done** |
| PG-003 | Database Inventory & Capacity | SYSTEM | SNAPSHOT | Medium | **Done** |
| PG-004 | Table & Index Capacity | DATABASE | SNAPSHOT | Medium | **Done** |
| PG-005 | Vacuum & Analyze Statistics | DATABASE | SNAPSHOT | Very High | **Done** |
| PG-006 | Transaction / Wraparound Health | SYSTEM / DATABASE | SNAPSHOT | Very High | **Done** |
| PG-007 | Replication & Slot Health | SYSTEM / NODE | SNAPSHOT | Very High | **Done** |
| PG-008 | Session & Connection Activity | SYSTEM / DATABASE | SNAPSHOT | High | **Done** |
| PG-009 | Locking / Long Transactions | DATABASE | SNAPSHOT / EVENT | Very High | **Partial** — long transactions via `PG_ACTIVITY_SNAPSHOT`; locking open |
| PG-010 | Index Inventory & Usage | DATABASE | SNAPSHOT | Very High | Planned |
| PG-011 | Index Quality | DATABASE | SNAPSHOT | Very High | Planned |
| PG-012 | pg_stat_statements Workload | DATABASE | SNAPSHOT / DELTA | Very High | Planned |
| PG-013 | Tablespace Capacity | NODE / SYSTEM | SNAPSHOT | High | Planned |
| PG-014 | Bloat / Fragmentation | DATABASE | SNAPSHOT | Very High | Planned |
| PG-015 | Extensions Inventory | DATABASE | SNAPSHOT | High | Planned |
| PG-016 | Roles & Security | SYSTEM / DATABASE | SNAPSHOT | Very High | Planned |
| PG-017 | SSL / HBA / Access Security | NODE | SNAPSHOT | Very High | **Partial** — `ssl`, `password_encryption` from the configuration snapshot; `pg_hba` open |
| PG-018 | Schema / Object Inventory | DATABASE | SNAPSHOT | Medium | Planned |
| PG-019 | Sequence Capacity | DATABASE | SNAPSHOT | Very High | Planned |
| PG-020 | Prepared Transactions | SYSTEM | SNAPSHOT | High | **Done** — `PG_PREPARED_TRANSACTIONS` |
| PG-021 | Partition Inventory | DATABASE | SNAPSHOT | Medium | Planned |
| PG-022 | FK / Constraint Health | DATABASE | SNAPSHOT | High | Planned |
| PG-023 | Function / Trigger Statistics | DATABASE | SNAPSHOT | Medium | Planned |
| PG-024 | Temp Objects / Temp Usage | DATABASE | SNAPSHOT | High | Planned |
| PG-025 | Large Objects Inventory | DATABASE | SNAPSHOT | Low | Planned |
| PG-026 | TOAST Mapping | DATABASE | SNAPSHOT | Low | Planned |
| PG-027 | Background Processes | NODE | SNAPSHOT | Medium | Planned |
| PG-028 | DB Load / Activity Profile | SYSTEM / DATABASE | SNAPSHOT / DELTA | Very High | Planned |
| PG-029 | Multixact Wraparound | SYSTEM / DATABASE | SNAPSHOT | Very High | **Done** — part of PG-006 (`mxid_age`) |
| PG-030 | Unlogged / Risky Objects | DATABASE | SNAPSHOT | High | Planned |
| PG-031 | Provider-specific Telemetry | SYSTEM / NODE | SNAPSHOT | Variable | Later |
| PG-032 | WAL Archiving & Timeline | NODE | SNAPSHOT | Very High | **Done** — `PG_WAL_STATUS` (archiver statistics, current timeline and when it began) |

## Current Development Focus

Implemented (2026-10-26): PG-001 to PG-008, PG-020, PG-029, PG-032, parts of PG-009 and PG-017, plus Linux host evidence (`PG_HOST_SNAPSHOT`) and per-session activity (`PG_ACTIVITY_SNAPSHOT`). Next: PG-010 / PG-011 indexes, PG-019 sequences, PG-016 / PG-018 roles and schema privileges, for the remaining P1 checks of the PostgreSQL V1 Assessment Catalogue.

Since 2026-10-05, new collector work is prioritised by the MVP Plan and by evidence needs of new rules rather than by this sequence.

Roadmap collector IDs describe functional collection capabilities and are independent from PostgreSQL provider repository migration versions. A single functional collector may require multiple repository migrations, and migration numbering may therefore advance independently from this roadmap.

Higher-level findings and recommendations will be developed on top of collected telemetry rather than embedded into individual collectors.