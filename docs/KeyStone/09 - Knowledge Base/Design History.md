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

## 2026-09-19 — Assessment, RCA, Dictionary, and Presentation Model

The architecture discussion moved beyond finding detection and clarified how Keystone should support repeatable database engineering assessment and root-cause analysis.

Key decisions and directions:

- Automation was decomposed logically into Target Management, Collector Framework, Scheduler, Execution Engine, and Evidence Repository.
- Engineering Intelligence is asynchronous from Presentation. Reusable derived evidence and engineering results should be persisted rather than recomputed from all historical telemetry for every user request.
- The engineering chain evolved to **Raw Evidence → Derived Evidence → Assessment → Finding → RCA → Recommendation → Proposed Action**.
- An assessment can explicitly be healthy, attention-required, or not assessed / insufficient evidence. Zero findings is not proof of complete health.
- RCA is distinct from finding detection. It evaluates hypotheses using supporting, contradicting, and missing evidence. Finding confidence, RCA confidence, and recommendation confidence are separate concepts.
- Collector design should gather enough evidence, where practical, to investigate likely causes rather than only detect conditions. Missing RCA evidence becomes an explicit collector/evidence gap.
- Findings and Recommendations are separate domain concepts. One Finding may have multiple Recommendations; Recommendations may contain ordered steps and may reuse Proposed Actions.
- The **Keystone Dictionary** was introduced as the engineering knowledge base containing generic engineering concepts plus provider-specific assessments, analyses, finding definitions, RCA models/evidence requirements, hypotheses, recommendations, and reusable action definitions.
- Provider knowledge remains provider-specific. Generic concepts may connect comparable concerns across PostgreSQL, SQL Server, MySQL, MongoDB, and future providers without forcing provider-native concepts into a false common model.
- AI Engineering Assistant reasoning should be grounded first in Keystone evidence, derived evidence, persisted engineering results, Dictionary knowledge, and history. AI may suggest additional hypotheses but must not invent missing evidence. AI-suggested hypotheses remain distinguishable from Dictionary-defined knowledge.
- Presentation was reframed as an engineering workspace rather than a raw telemetry dashboard. Candidate views are Estate Overview, System Engineering View, Finding / Investigation Workspace, and Change & History Explorer.
- Action execution was intentionally deferred until the Presentation model is established. The previously defined human decision boundary remains unchanged.
- One-off Health Check and continuous Keystone operation should not become separate engineering engines. The same platform supports **Snapshot Assessment**, **Temporary Observation**, and **Continuous Engineering** modes. Assessment Profiles determine required checks, evidence, and collector coverage.

This discussion also changed the preferred development-planning method. Instead of extending collector count sequentially without reference to engineering outcomes, V1 should be designed backward from **Assessment Catalogue → Findings/RCA → Required Evidence → Evidence Coverage → Collector Gaps**.

## Open Design Work

The following areas remain intentionally open until module design is completed:

- scheduler implementation and scheduling policy,
- finalize technical module boundaries where implementation requires stronger separation,
- define the PostgreSQL V1 Assessment Catalogue,
- define the V1 Findings and RCA catalogue,
- build the Evidence Coverage Matrix against implemented collectors,
- identify collector gaps and derive the next collector roadmap from evidence needs,
- define V1 scope for each module,
- determine development order after the assessment/evidence gap analysis,
- concrete AI Engineering Assistant implementation architecture and model/tool boundaries.

When decisions are made, they should be captured in current architecture documents and, where significant, new ADRs. This history should remain as context rather than being rewritten to make the past look identical to the final design.
