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

This was formalized by ADR-0010. The same evidence may later support health assessment, performance engineering, trend analysis, recommendations, reporting, or proposed actions.

## 2026-09-18 — Architecture Convergence

The high-level Keystone model was clarified into three architectural concerns:

1. **Automation** — Collection → Scheduling → Execution → Repository
2. **Engineering Intelligence** — deterministic rules, statistical analysis, ML, correlation, engineering logic, findings, and recommendations
3. **Presentation and Action** — reports, findings, recommendations, proposed actions, and human-controlled operational decisions

UI and API were explicitly treated as cross-cutting interaction mechanisms rather than a fourth pipeline stage.

The AI direction was also clarified. The main Keystone product may include an **AI Engineering Assistant** spanning Engineering Intelligence and Presentation. The Assistant can use Keystone evidence, history, findings, recommendations, and engineering context to explain, summarize, compare, correlate, and support natural-language interactive analysis.

AI is intentionally not the source of truth. Deterministic and statistical methods remain first-class engineering mechanisms, and AI is used where contextual reasoning or natural-language interaction adds value.

A human decision boundary was established for remediation: Keystone may recommend and prepare proposed actions, but it does not autonomously change production environments.

## 2026-09-18 — Keystone AI Agents Concept

A separate product idea emerged during the AI architecture discussion: **Keystone AI Agents**.

The concept is distinct from the AI Engineering Assistant in the main Keystone product.

- **AI Engineering Assistant:** interacts with evidence and engineering intelligence already available to Keystone.
- **Keystone AI Agents:** future autonomous read-only diagnostic investigation, capable of requesting or executing approved diagnostics to investigate a problem or perform root-cause analysis.

The AI Agents concept has a materially different security and testing profile. It must remain read-only for investigation and must not autonomously remediate target environments.

This is recorded as a **future / separate product concept**, not as current Keystone scope or V1 commitment.

## Open Design Work

The following areas remain intentionally open until module design is completed:

- scheduler implementation and scheduling policy,
- final technical module boundaries inside Automation, Engineering Intelligence, and Presentation,
- customer-facing product/capability module boundaries,
- V1 scope for each module,
- development order after the current collection foundation,
- concrete AI Engineering Assistant implementation architecture and model/tool boundaries.

When decisions are made, they should be captured in current architecture documents and, where significant, new ADRs. This history should remain as context rather than being rewritten to make the past look identical to the final design.
