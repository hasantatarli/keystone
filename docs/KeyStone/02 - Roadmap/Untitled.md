| ID     | Keystone Collector              | Scope             | Data Type        | Tarihsel Değeri | Finding Potansiyeli | Öncelik |
| ------ | ------------------------------- | ----------------- | ---------------- | --------------- | ------------------- | ------- |
| PG-001 | Instance Inventory              | NODE              | CURRENT          | Düşük           | Düşük               | ✅ Var   |
| PG-002 | Configuration Snapshot          | NODE              | SNAPSHOT         | **Çok yüksek**  | **Yüksek**          | P1      |
| PG-003 | Database Inventory & Capacity   | SYSTEM / DATABASE | SNAPSHOT         | **Çok yüksek**  | Orta                | P1      |
| PG-004 | Table & Index Capacity          | DATABASE          | SNAPSHOT         | **Çok yüksek**  | Orta                | P1      |
| PG-005 | Vacuum & Analyze Statistics     | DATABASE          | SNAPSHOT         | **Çok yüksek**  | **Çok yüksek**      | P1      |
| PG-006 | Transaction / Wraparound Health | SYSTEM / DATABASE | SNAPSHOT         | Yüksek          | **Çok yüksek**      | P1      |
| PG-007 | Replication & Slot Health       | SYSTEM / NODE     | SNAPSHOT         | **Çok yüksek**  | **Çok yüksek**      | P1      |
| PG-008 | Session & Connection Activity   | SYSTEM / DATABASE | SNAPSHOT         | Yüksek          | Yüksek              | P1      |
| PG-009 | Locking / Long Transactions     | DATABASE          | SNAPSHOT / EVENT | **Çok yüksek**  | **Çok yüksek**      | P1      |
| PG-010 | Index Inventory & Usage         | DATABASE          | SNAPSHOT         | **Çok yüksek**  | **Çok yüksek**      | P1      |
| PG-011 | Index Quality                   | DATABASE          | SNAPSHOT         | Orta            | **Çok yüksek**      | P1      |
| PG-012 | pg_stat_statements Workload     | DATABASE          | SNAPSHOT / DELTA | **Çok yüksek**  | **Çok yüksek**      | P1/P2   |
| PG-013 | Tablespace Capacity             | NODE / SYSTEM     | SNAPSHOT         | Yüksek          | Yüksek              | P2      |
| PG-014 | Bloat / Fragmentation           | DATABASE          | SNAPSHOT         | Yüksek          | **Çok yüksek**      | P2      |
| PG-015 | Extensions Inventory            | DATABASE          | SNAPSHOT         | Orta            | Yüksek              | P2      |
| PG-016 | Roles & Security                | SYSTEM / DATABASE | SNAPSHOT         | **Yüksek**      | **Çok yüksek**      | P2      |
| PG-017 | SSL / HBA / Access Security     | NODE              | SNAPSHOT         | Orta            | **Çok yüksek**      | P2      |
| PG-018 | Schema / Object Inventory       | DATABASE          | SNAPSHOT         | Orta            | Orta                | P2      |
| PG-019 | Sequence Capacity               | DATABASE          | SNAPSHOT         | **Yüksek**      | **Çok yüksek**      | P2      |
| PG-020 | Prepared Transactions           | SYSTEM / DATABASE | SNAPSHOT         | Orta            | Yüksek              | P2      |
| PG-021 | Partition Inventory             | DATABASE          | SNAPSHOT         | Yüksek          | Orta                | P2      |
| PG-022 | FK / Constraint Health          | DATABASE          | SNAPSHOT         | Orta            | Yüksek              | P2      |
| PG-023 | Function / Trigger Statistics   | DATABASE          | SNAPSHOT         | Yüksek          | Orta                | P3      |
| PG-024 | Temp Objects / Temp Usage       | DATABASE          | SNAPSHOT         | Yüksek          | Yüksek              | P3      |
| PG-025 | Large Objects Inventory         | DATABASE          | SNAPSHOT         | Orta            | Düşük               | P3      |
| PG-026 | TOAST Mapping                   | DATABASE          | SNAPSHOT         | Düşük           | Düşük               | P3      |
| PG-027 | Background Processes            | NODE              | SNAPSHOT         | Orta            | Orta                | P3      |
| PG-028 | DB Load / Activity Profile      | SYSTEM / DATABASE | SNAPSHOT / DELTA | **Çok yüksek**  | **Çok yüksek**      | P2      |
| PG-029 | Multixact Wraparound            | SYSTEM / DATABASE | SNAPSHOT         | Yüksek          | **Çok yüksek**      | P2      |
| PG-030 | Unlogged / Risky Objects        | DATABASE          | SNAPSHOT         | Orta            | Yüksek              | P3      |
| PG-031 | Provider-specific Telemetry     | SYSTEM / NODE     | SNAPSHOT         | Değişken        | Değişken            | Later   |