# ADR-0007 — Cross-Platform Provider Architecture

**Status:** Approved — implementation approach amended  
**Date:** 2026-08-05  
**Amended:** 2026-09-04

## Context

DataWiser supports database platforms running across Windows and Linux environments. A platform tied to one operating system or database engine would restrict Keystone's ability to support those services consistently.

## Decision

Keystone will use a shared, cross-platform core with database-specific providers.

The common platform owns provider-independent concepts such as targets, connections, collector definitions, assignments, execution coordination, and run history. Providers own database-specific collection knowledge and repository structures.

Common abstractions should be introduced when repeated provider or execution behavior justifies them rather than being designed speculatively.

## Implementation Amendment

The original ADR anticipated a future .NET core, provider-local scheduling, and an initial SQL/shell-oriented PostgreSQL implementation.

Development has since established a Python-based execution core, a central PostgreSQL repository, and a queue/worker execution model. These implementation choices replace those original assumptions without changing the underlying architectural decision: a shared cross-platform core with isolated database providers.

The architecture does not require future providers to use database-native schedulers or provider-local repositories.

## Consequences

- Database-specific knowledge remains isolated inside providers.
- Core execution concepts can be reused across PostgreSQL and future providers.
- Provider telemetry can evolve independently while sharing central orchestration.
- The implementation language and runtime mechanisms can evolve without redefining the provider boundary.
- Cross-platform support remains an architectural requirement rather than an operating-system-specific implementation choice.