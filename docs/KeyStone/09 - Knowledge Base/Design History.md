# Keystone Design History

**Status:** Living Record  
**Purpose:** Preserve significant historical design direction, including assumptions later amended or superseded.

## Why This Record Exists

Keystone architecture evolves through implementation and real engineering needs. Approved ADRs remain the source of current architectural decisions, but earlier approaches should not disappear when an implementation changes.

This document records important historical direction so future design work can distinguish what was originally intended, what was implemented, what was later amended, and what remains undecided. It is not a replacement for ADRs or current architecture documents.

## 2026-08 — Initial Foundation Direction

The initial development strategy was foundation-first and PostgreSQL-first.

The intended progression was broadly:

**Collector / Repository Foundation → Scheduling and Repeatable Execution → Historical Evidence → Viewer / Reporting → Engineering Interpretation and Higher-Level Capabilities**

Important early assumptions included:

- PostgreSQL as the first provider.
- Historical repository and reusable collectors before customer-facing presentation.
- Portal/dashboard and AI-assisted capabilities deferred until the collection foundation became useful.
- Collection designed as reusable platform capability rather than one-off scripts.
- Automated installation and upgrade rather than manual repository object deployment.
- Cross-platform/provider-oriented architecture rather than a PostgreSQL/Linux-only product.

Some implementation details from this period were later amended by ADR-0006 and ADR-0007. In particular, deployment ownership was separated from runtime execution, and the runtime converged on a Python core, central PostgreSQL repository, and queue/worker model.

## 2026-08 to 2026-09 — Execution Foundation Evolution

As collectors were implemented, the platform core evolved to support repeatable execution at larger scale.

The implemented direction includes target and connection inventory, collector definitions separated from target assignments, a central execution queue, generic worker execution, stable collector keys, SYSTEM / NODE / DATABASE execution scopes, database-scoped fan-out, task ownership and worker heartbeat, stale execution recovery, bounded retries, explicit failure states, PARTIAL_SUCCESS for database-scoped collection, central run history, and provider-specific telemetry persistence.

This reflects an incremental development pattern: advance provider collection, strengthen the shared foundation when a concrete execution need appears, then continue provider coverage.

## PostgreSQL Functional Collector Progress

Functional collector roadmap IDs are independent from provider repository migration versions.

As of 2026-09-18, the implemented PostgreSQL functional baseline is:

- PG-001 — Instance Inventory
- PG-002 — Configuration Snapshot
- PG-003 — Database Inventory & Capacity
- PG-004 — Table & Index Capacity
- PG-005 — Vacuum & Analyze Statistics
- PG-006 — Transaction / Wraparound Health
- PG-007 — Replication & Slot Health
- PG-008 — Session & Connection Activity

The latest PostgreSQL provider repository migration is PG011 because some functional collectors required more than one repository migration. The next functional roadmap item is PG-009 — Locking / Long Transactions.

## Interpretation Boundary

A stable design principle emerged during the collection work:

> Collectors persist observable technical facts. Engineering conclusions derived from those facts belong above the collection layer.

This was formalized by ADR-0010. The same evidence may later support health assessment, performance engineering, trend analysis, recommendations, reporting, or controlled actions.

## Open Design Work

The following areas are intentionally not recorded here as final decisions because their architecture and product boundaries still need to be clarified:

- scheduler architecture and scheduling policy,
- management UI / API boundaries,
- final platform module boundaries,
- customer-facing product/capability module boundaries,
- V1 scope for each module,
- development order after the current collection foundation.

When decisions are made, they should be captured in current architecture documents and, where significant, new ADRs. This history should remain as context rather than being rewritten to make the past look identical to the final design.
