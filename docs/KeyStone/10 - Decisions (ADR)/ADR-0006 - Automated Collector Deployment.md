# ADR-0006 — Automated Collector Deployment

**Status:** Approved — implementation approach amended  
**Date:** 2026-08-05  
**Amended:** 2026-09-04

## Context

Keystone repository structures and collectors must evolve consistently across installations. Manual object-by-object deployment would be slow, inconsistent, and difficult to upgrade safely.

## Decision

Keystone uses an automated, migration-driven deployment model for repository structures and collector registration.

Core migrations and provider migrations evolve independently. Pending migrations are discovered and applied by the installer, and collector definitions are registered from provider metadata.

A migration is considered installed only when its database changes and successful migration-history record are committed together.

## Implementation Amendment

The original ADR also assigned scheduling, initial execution, validation, and uninstallation to the collector deployment mechanism.

The current architecture separates those responsibilities. The installer owns repository evolution and collector registration. Runtime scheduling, collector execution, task recovery, and credential handling belong to the runtime platform.

Future deployment automation may add higher-level lifecycle operations, but they should not be embedded inside migration scripts.

## Consequences

- Repository installation and upgrades are repeatable.
- Failed migrations do not leave silently accepted partial repository state.
- Core and provider schemas can evolve independently.
- Collector registration is metadata-driven rather than manual.
- Runtime operations remain separate from schema migration ownership.