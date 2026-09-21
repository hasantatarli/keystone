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

## Next Design Decisions

- Confirm top-level capability domains and boundaries.
- Decide which capabilities are included in Keystone V1.
- Define V1 profiles / services.
- Define the PostgreSQL V1 Assessment Catalogue.
- Define Findings and RCA models.
- Build the Evidence Coverage Matrix against existing PostgreSQL collectors.
- Derive collector gaps and the next PostgreSQL collector roadmap.
