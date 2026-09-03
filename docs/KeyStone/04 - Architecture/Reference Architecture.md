# Keystone Reference Architecture

**Status:** Draft  
**Version:** 0.1

## Purpose

Keystone is a provider-agnostic database engineering platform designed to collect technical facts from database environments, preserve them centrally, and turn them into findings, recommendations, and eventually controlled engineering actions.

The architecture separates data collection from interpretation. Collectors gather facts; findings and recommendations are produced by separate engineering logic.

## Architectural Model

Keystone is organized around four main layers:

1. **Targets and Connections** — describe the database systems and nodes Keystone can reach.
2. **Collectors and Execution** — define what is collected and at which execution scope it runs.
3. **Repository** — stores Keystone metadata, execution history, and provider-specific telemetry.
4. **Engineering Logic** — evaluates collected facts and produces findings, recommendations, and future actions.

The current implementation uses a central PostgreSQL repository and a Python-based worker that executes registered collectors against assigned targets.

## Provider Architecture

Database-specific behavior is implemented through providers.

The Keystone core owns generic concepts such as targets, connections, collector definitions, assignments, queueing, execution history, and credential handling.

Each provider owns its database-specific collectors, repository objects, migrations, and persistence logic.

The initial provider is PostgreSQL. The architecture is intended to support additional providers such as SQL Server, MySQL, and MongoDB without changing the core execution model.

## Target Topology

Keystone models database environments using two topology levels:

- **SYSTEM** — a logical database system, standalone instance, or cluster.
- **NODE** — an individual database server or cluster member when node-specific collection is required.

A database inside a database system is not modeled as a separate target.

Target topology describes the environment. It does not define how every collector executes.

## Collector Execution Scope

Collector execution scope is independent from target topology.

Collectors can execute at:

- **SYSTEM** — once for a logical database system or cluster.
- **NODE** — once for an individual node.
- **DATABASE** — once for each connectable database discovered within a system.

DATABASE-scoped collectors are assigned to a SYSTEM target and fan out dynamically across its databases. This avoids creating and maintaining separate Keystone targets for every database.

## Execution Model

Collector assignments determine which collectors run against which targets.

Execution requests are placed into a central queue. Workers claim eligible tasks, execute the appropriate collector, persist the results, and record execution history.

The worker model supports parallel execution, task ownership, heartbeat-based liveness detection, stale-task recovery, and bounded retries.

Database-scoped execution uses best-effort fan-out: an individual database failure does not prevent successful databases from being collected. Partial execution is represented explicitly rather than hidden as success.

## Repository Model

The central repository separates generic Keystone metadata from provider-specific telemetry.

- The **`keystone` schema** contains platform metadata and execution control data.
- Provider schemas, such as **`postgresql`**, contain provider-specific inventory and telemetry.

Repository data is intentionally separated into current-state and historical snapshot models depending on the nature of the collector.

The repository is the system of record for collected engineering facts and execution history.

## Collection and Interpretation

Collectors are responsible for collecting observable facts from the target environment.

They should not embed business conclusions such as risk level, health score, growth classification, or remediation advice unless the value itself is a direct database fact.

Interpretation belongs to a separate engineering layer:

**Collector → Finding → Recommendation → Action**

This allows deterministic engineering rules, future anomaly detection, and AI-assisted analysis to operate on the same normalized evidence without coupling interpretation to data collection.

## Security Model

Connections are stored separately from targets and describe how Keystone reaches an environment.

Credentials that must be recoverable for database connectivity are encrypted before storage. The encryption key is kept outside the repository so that a repository backup alone is insufficient to recover credentials.

The architecture is designed to support additional authentication mechanisms and external secret-management systems without changing the target model.

## Migration and Deployment Model

Core and provider database objects are versioned independently.

Core migrations evolve the Keystone platform schema. Provider migrations evolve provider-specific repository structures.

Migrations are executed transactionally so that a failed migration does not leave a partially applied repository state.

Collectors are discovered and registered from provider metadata rather than being hardcoded into the repository.

## Architectural Principles

- Provider-agnostic core, provider-specific implementation.
- Target topology and collector execution scope are separate concepts.
- Databases are execution units, not Keystone targets.
- Collect facts before interpreting them.
- Keep provider telemetry separate from platform metadata.
- Prefer stable metadata-driven execution over collector-specific branching.
- Preserve execution history and failure visibility.
- Introduce abstractions when repeated implementation needs justify them.
- Keep the architecture simple enough to evolve from real customer requirements.
