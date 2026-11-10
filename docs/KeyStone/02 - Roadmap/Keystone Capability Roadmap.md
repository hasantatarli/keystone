# Keystone Capability Roadmap

**Status:** Draft  
**Last Updated:** 2026-09-21

## Purpose

Define what engineering capabilities Keystone is intended to provide before those capabilities are decomposed into assessment profiles, findings, RCA models, evidence requirements, collectors, and implementation work.

This roadmap is product-oriented. It is not a collector roadmap and does not imply that every capability is part of V1.

## Capability Model

Keystone distinguishes three levels:

**Capability** — what Keystone can do as a database engineering platform.

**Profile / Service** — how capabilities are packaged for a specific engineering purpose or customer engagement.

**Assessment / Investigation Run** — execution of a profile against a specific customer target.

Collectors do not belong exclusively to a capability. They produce reusable engineering evidence that may support multiple capabilities and profiles.

## Engineering Capability Domains

### 1. Health & Assessment

- General Health Assessment
- Configuration Assessment
- Maintenance Assessment
- Reliability Assessment
- Architecture Assessment

### 2. Performance Engineering

- Performance Baseline
- Workload Analysis
- Query Performance Analysis
- Wait / Lock / Concurrency Analysis
- Resource Correlation
- Performance Regression Detection
- Performance Investigation / RCA

### 3. Capacity Engineering

- Storage / Database Growth
- Table / Index Growth
- Resource Utilization Trends
- Capacity Risk Detection
- Capacity Forecasting

### 4. HA / DR Engineering

- Replication Health
- HA Readiness
- Failover Readiness
- DR Readiness
- RPO / RTO Assessment
- Topology / Resilience Assessment

### 5. Backup & Recovery Engineering

- Backup Health
- Backup Policy Assessment
- Recovery Readiness
- Restore Validation
- Recovery Risk Assessment

### 6. Security Engineering

- Security Assessment
- Authentication Assessment
- User / Role / Privilege Analysis
- Configuration Hardening
- Exposure / Access Risk
- Compliance Evidence

### 7. Upgrade & Lifecycle Engineering

- Version / EOL Assessment
- Upgrade Readiness
- Compatibility Analysis
- Extension / Feature Compatibility
- Upgrade Risk
- Upgrade Planning

### 8. Operations Engineering

- Maintenance Operations
- Operational Health
- Standard Runbooks
- Change Preparation
- Proposed Actions

## Cross-Cutting Platform Capabilities

These enable the engineering domains but are not equivalent customer-facing capability domains:

### Engineering Intelligence

- Change Detection
- Trend Analysis
- Cross-domain Correlation
- Finding Lifecycle
- RCA / Hypothesis Analysis
- Recommendation Generation

### Platform Foundations

- Target Management
- Collector Framework
- Scheduler
- Execution Engine
- Evidence Repository
- Intelligence Repository
- Keystone Dictionary
- Presentation
- UI / API
- AI Engineering Assistant

## Candidate Profiles / Services

Capabilities may be composed into profiles such as:

- PostgreSQL Health Assessment
- PostgreSQL Performance Investigation
- PostgreSQL Security Assessment
- PostgreSQL HA/DR Assessment
- PostgreSQL Upgrade Readiness
- PostgreSQL Capacity Assessment
- Continuous Database Engineering

Provider names identify the implementation context, not separate platform architectures.

## Health Assessment Position

Health Assessment is not the whole Keystone product.

It is a broad assessment profile that uses multiple engineering capabilities at an appropriate depth. For example, it may inspect performance and security indicators without replacing a dedicated Performance Investigation or Security Assessment.

## Evidence Reuse Principle

A collector produces reusable evidence rather than capability-specific output.

The same evidence may support different engineering questions. For example, connection activity may contribute to Health Assessment, Performance Engineering, Capacity Engineering, and Continuous Engineering.

Provider-specific engineering knowledge remains provider-specific even when multiple providers implement the same high-level capability.

## Roadmap Derivation

Implementation planning should flow from engineering purpose rather than arbitrary collector sequence:

**Capability Map → V1 Product Scope → Profiles → Assessment / Investigation Catalogue → Findings → RCA Models → Evidence Requirements → Evidence Coverage Matrix → Collector Gaps → Collector Roadmap → Implementation**

Existing collector roadmap IDs remain valid, but future collector work should be justified by evidence requirements derived from this model.

## Long-Term Direction (2026-11-10)

Recorded from a discussion with Hasan; a direction, not a change of the current plan. P2 and P3 come first.

### What customers ask for

Requests reaching DataWiser go beyond a health check. Customers buy a decision: what do we have, is it safe, can we recover, should we stay on this platform or move. A recent request (managed PostgreSQL, hosting review) asked for:

- a technical inventory: schemas, tables, relationships, indexes, extensions, migration history;
- an access review: roles, grants, row-level security;
- backup and recovery arrangements, including what SQL cannot see (platform backups, restore tests);
- hosting options and migration readiness;
- a report an independent assessor can verify.

Assessment layers that follow from this, the health check being one of them:

| Layer | Question | Status |
|---|---|---|
| Health | Is something wrong? | Strong (31 rules) |
| Inventory | What exactly do we have? | Missing |
| Security and access | Who can reach what? | Partial |
| Backup and recovery | Can we really recover? | Partial (what SQL shows) |
| Platform and portability | Can this move to RDS / Azure; what blocks it? | Missing |
| Evidence quality | Can an independent reviewer verify it? | Foundation present (capture times, file checksums), not in the report |

Two concepts this needs:

- **Stated facts:** information SQL cannot see (platform backups, last restore test, host facts without access) enters the report labelled as stated by the customer, never mixed with measured evidence.
- **Portability checks:** unsupported extensions on a target platform, tables without a primary key (block logical replication), version gaps. Deterministic rules that answer "stay or move" objectively.

Hosting cost comparison and migration plans stay consulting deliverables; Keystone supplies their facts.

### Continuous engineering and screens

A SQL Server tool used by DBA consultancies (company and server tree, wait statistics, disk IO, procedures whose reads grew against last week, AG node comparison with fix scripts) shows the target: the value is in time, answering what changed, why, and what to do.

Already in place: collectors run on a clock-aligned schedule (ADR-0015, V025); collectors store raw counters with no filtering in SQL; assessments run on schedule and keep their history (V026).

Missing, the engineering layer:

1. **Derived evidence:** differences and rates between snapshots (TPS, growth per day). Rules mostly read one snapshot today.
2. **Baselines and trends:** is this normal for this system; what changed since last week.
3. **Performance time-series collectors:** `pg_stat_statements` deltas (regressed queries), wait-event sampling, blocking samples.
4. **Retention and rollup:** deferred in V024 until continuous operation produces volume.
5. **Screens:** today only the HTML report. Screens are needed to explore, not only to read a report.

Host CPU and memory monitoring is left to existing tools (Zabbix, Prometheus); Keystone shows the inside of the database.

PostgreSQL counterparts of the most valuable screens, in order: regressed queries (`pg_stat_statements`), growth trend and forecast, Patroni node comparison (configuration is already collected per node), wait sampling, blocking.

Positioning: one tool for DBAs and consultancies managing many customers: company, server, rule, recommendation, fix command, offline mode.

### AI assistant

ADR-0012 already defines it. The intended interaction: a metric is high on a screen; the user asks "how was this at the same time last month?" and gets an answer built from Keystone's own history and findings, with the evidence it used. This depends on layers 1-3 above: the assistant explains derived evidence and history; it does not invent numbers.

### Sequence

1. P2 and P3 rules. Derived evidence and baselines are built when a rule first needs them (for example a capacity rule that needs a growth trend), not as a separate project.
2. Inventory, access review, platform profile, evidence appendix (assessment report level).
3. Stated facts with the backup section; portability checks.
4. Performance time-series collectors, retention, screens.
5. AI assistant over the history (ADR-0012); comparison between two checks; estate overview (ADR-0016); a second provider.

## Next Design Decisions

- Confirm top-level capability domains and boundaries.
- Decide which capabilities are included in Keystone V1.
- Define V1 profiles / services.
- Define the PostgreSQL V1 Assessment Catalogue.
- Define Findings and RCA models.
- Build the Evidence Coverage Matrix against existing PostgreSQL collectors.
- Derive collector gaps and the next PostgreSQL collector roadmap.
