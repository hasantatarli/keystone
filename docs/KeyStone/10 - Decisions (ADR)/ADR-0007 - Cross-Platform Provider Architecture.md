**Status:** Approved  
**Date:** 2026-08-05

## Context

DataWiser supports database platforms running across Windows and Linux environments.

SQL Server commonly runs on Windows, while PostgreSQL, MySQL and MongoDB commonly run on Linux. A platform tied to one operating system would restrict Keystone's ability to support DataWiser services consistently.

## Decision

Keystone will use:

- A cross-platform core
- Database-specific providers
- Environment-specific scheduler and deployment adapters

The preferred future implementation technology for the Keystone Core is .NET 8 with C#.

The initial PostgreSQL implementation may use SQL and shell scripts before repeated lifecycle logic is moved into the common core.

## Consequences

- The user-facing lifecycle remains consistent across platforms.
- Database-specific logic remains isolated inside providers.
- PostgreSQL development can begin without waiting for the complete framework.
- SQL Server can use SQL Server Agent while PostgreSQL uses cron or pg_cron.
- A permanent agent is not required in the initial release.
- Common abstractions will be extracted only after real provider implementations reveal repeated behavior.