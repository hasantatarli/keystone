# Technology Architecture

**Status:** Current  
**Version:** 0.1  
**Project:** Keystone  
**Last Updated:** 2026-09-04

## Architectural Direction

Keystone is a provider-oriented database engineering platform with a shared execution and repository core.

The core coordinates targets, connections, collector definitions, assignments, execution, run history, and provider integration. Database-specific behavior remains inside providers.

PostgreSQL is the first implemented provider. Additional providers such as SQL Server, MySQL, and MongoDB can be added without changing the fundamental execution model.

## Core Technology

The current Keystone execution and installation components are implemented in Python.

PostgreSQL is used as the central Keystone repository. It stores shared platform metadata and provider telemetry while keeping those concerns separated by schema.

The architecture does not depend on a future application or portal technology. CLI, API, UI, reporting, and automation interfaces can be added around the same repository and execution model.

## Provider Model

Each database technology has its own provider containing database-specific collectors, repository migrations, and collection semantics.

Provider code is responsible for understanding the target database technology. Generic orchestration concerns remain in the Keystone core.

This boundary is intended to allow new providers to reuse the same target, assignment, queue, worker, history, and security concepts.

## Repository Model

Keystone uses one central PostgreSQL repository.

The `keystone` schema contains provider-independent platform metadata and execution state. Provider schemas, such as `postgresql`, contain provider-specific inventory and telemetry.

Repository data is intentionally separated into two broad forms:

- **Current state** for facts where only the latest known state is required.
- **Snapshots** for telemetry where historical comparison and trend analysis are valuable.

## Execution Technology

Collectors are registered as definitions and assigned to targets. Executions are coordinated through the Keystone collection queue and processed by workers.

Target topology and execution scope are separate concepts:

- Target topology: `SYSTEM`, `NODE`
- Collector execution scope: `SYSTEM`, `NODE`, `DATABASE`

Database-scoped collectors do not require database targets. A SYSTEM assignment discovers the currently connectable databases and executes the collector against them individually.

This keeps database inventory dynamic while avoiding a large target hierarchy that mirrors every database.

## Worker Model

Workers claim eligible queued tasks and execute collectors independently. Multiple tasks can be processed concurrently.

Running tasks use heartbeat-based liveness detection. Tasks abandoned by a worker can be recovered and retried within a bounded retry policy.

Execution history is retained separately from the active queue so operational state and historical evidence remain distinct.

## Credential Model

Target connection metadata is stored centrally. Authentication behavior is selected through an authentication type.

Password credentials are stored encrypted and decrypted only when a connection is required. The encryption master key is intentionally kept outside the Keystone repository so a repository backup alone is not sufficient to recover credentials.

The model is designed to allow additional credential backends, such as external secret stores, without changing target definitions.

## Collection and Interpretation

Collectors are responsible for collecting factual database state and telemetry. They should not embed business interpretation merely because a metric can be derived during collection.

Keystone's intended engineering pipeline is:

**Collection → Finding → Recommendation → Action**

Collection is the currently implemented foundation. Findings, recommendations, and actions are higher-level capabilities that will be built on top of collected evidence.

## Principle

**Shared platform core, provider-specific database knowledge.**

Keystone should introduce abstractions when they solve repeated engineering problems, not in anticipation of hypothetical future requirements.