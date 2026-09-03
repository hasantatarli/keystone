**Status:** Draft  
**Version:** 0.1  
**Project:** Keystone  
**Last Updated:** 2026-08-05

## Architectural Direction

Keystone will use a cross-platform core with database-specific providers and environment-specific adapters.

The platform lifecycle will remain consistent across technologies:

- Deploy
- Validate
- Status
- Upgrade
- Repair
- Uninstall

Provider implementations may differ based on the target technology and operating environment.

## Core Technology

The preferred implementation technology for the future Keystone Core is .NET 8 with C#.

Reasons:

- Cross-platform support for Windows and Linux
- Existing DataWiser development expertise
- Strong database connectivity libraries
- Support for CLI, API and future portal development
- Testability and maintainability
- Single-file executable deployment options

## Provider Model

Each database technology will have its own provider.

Initial providers may include:

- PostgreSQL
- SQL Server
- MySQL
- MongoDB

Each provider is responsible for:

- Database-specific collectors
- Repository objects
- Permission requirements
- Scheduler integration
- Installation validation
- Upgrade and removal logic

## Scheduler Model

Keystone does not require a single scheduler technology.

Scheduler adapters will support the native capabilities of each environment.

| Provider | Possible Schedulers |
|---|---|
| PostgreSQL | cron, pg_cron, systemd timer |
| SQL Server | SQL Server Agent |
| MySQL | Event Scheduler, cron |
| MongoDB | cron, systemd timer |

## Repository Strategy

The initial implementation will prefer provider-local repositories to minimize customer dependencies.

Future options may include:

- SQLite for lightweight local deployments
- PostgreSQL for sidecar or centralized repositories
- Central DataWiser repositories where security and regulatory requirements allow

## Agent Strategy

Keystone will initially operate without a permanently installed agent wherever possible.

Operating-system metrics may be obtained through:

- Existing monitoring platforms
- SSH or WinRM
- A future lightweight Keystone Agent when justified

A dedicated agent is not part of the initial scope.

## Principle

Generic lifecycle, provider-specific implementation.
