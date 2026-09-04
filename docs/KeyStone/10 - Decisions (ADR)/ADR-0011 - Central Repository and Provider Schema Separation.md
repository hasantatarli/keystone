# ADR-0011 — Central Repository and Provider Schema Separation

**Status:** Approved  
**Date:** 2026-09-04

## Context

Keystone requires shared orchestration data while each database provider produces telemetry with different structures and semantics.

Provider-local repositories would simplify isolated deployments but fragment execution history, target configuration, and future cross-provider analysis.

## Decision

Keystone uses a central PostgreSQL repository.

Provider-independent platform metadata and execution state are stored in the `keystone` schema. Database-specific inventory and telemetry are stored in provider-owned schemas such as `postgresql`.

Core and provider repository migrations evolve independently.

## Consequences

- Targets, assignments, queue state, and run history use one common platform model.
- Providers can own database-specific telemetry without forcing it into an artificial generic schema.
- New providers can be installed without requiring unrelated provider schemas.
- Cross-provider reporting and future platform services have a common repository foundation.
- Repository availability and security become platform-level operational concerns.