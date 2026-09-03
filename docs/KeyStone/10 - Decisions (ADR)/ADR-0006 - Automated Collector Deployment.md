**Status:** Approved  
**Date:** 2026-08-05

## Context

Historical engineering telemetry requires multiple database objects, permissions, and scheduled collection jobs.

Creating these components manually for every customer would be slow, inconsistent, and error-prone.

## Decision

Keystone will provide a single deployment mechanism for each collector package.

The deployment mechanism must:

- Install all required objects
- Configure scheduled collection
- Validate the installation
- Support repeatable execution
- Support version upgrades
- Support controlled uninstallation

## Consequences

- Customer installations become repeatable.
- Manual setup effort is reduced.
- Collector versions can be managed consistently.
- Deployment and rollback must be treated as first-class engineering capabilities.