# Technology Architecture

**Status:** Current  
**Version:** 0.2  
**Project:** Keystone  
**Last Updated:** 2026-09-18

## Architectural Direction

Keystone is a provider-oriented database engineering platform with a shared execution and repository core.

The platform is organized conceptually into three layers:

1. **Automation** — Collection → Scheduling → Execution → Repository
2. **Engineering Intelligence** — rules, statistical analysis, ML, correlation, engineering logic, findings, and recommendations
3. **Presentation and Action** — reports, findings, recommendations, proposed actions, and human-controlled operational decisions

The core coordinates targets, connections, collector definitions, assignments, scheduling/orchestration, execution, run history, and provider integration. Database-specific behavior remains inside providers.

PostgreSQL is the first implemented provider. Additional providers such as SQL Server, MySQL, and MongoDB can be added without changing the fundamental execution model.

## Core Technology

The current Keystone execution and installation components are implemented in Python.

PostgreSQL is used as the central Keystone repository. It stores shared platform metadata and provider telemetry while keeping those concerns separated by schema.

The architecture does not depend on a future application or portal technology. CLI, API, UI, reporting, and automation interfaces can be added around the same repository, execution, and engineering intelligence model.

UI and API are considered cross-cutting interaction mechanisms and may expose capabilities from all three architectural layers.

## Provider Model

Each database technology has its own provider containing database-specific collectors, repository migrations, collection semantics, and provider-specific engineering knowledge where appropriate.

Provider code is responsible for understanding the target database technology. Generic orchestration concerns remain in the Keystone core.

This boundary is intended to allow new providers to reuse the same target, assignment, scheduling, queue, worker, history, security, and engineering concepts.

## Repository Model

Keystone uses one central PostgreSQL repository.

The `keystone` schema contains provider-independent platform metadata and execution state. Provider schemas, such as `postgresql`, contain provider-specific inventory and telemetry.

Repository data is intentionally separated into two broad forms:

- **Current state** for facts where only the latest known state is required.
- **Snapshots** for telemetry where historical comparison and trend analysis are valuable.

The repository provides the evidence and history consumed by Engineering Intelligence and the AI Engineering Assistant.

## Execution Technology

Collectors are registered as definitions and assigned to targets. Executions are coordinated through the Keystone collection queue and processed by workers.

Scheduling is a distinct Automation responsibility: it determines when recurring assignments should produce execution requests. The continuously running scheduler implementation remains future work.

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

## Engineering Intelligence

Collectors are responsible for collecting factual database state and telemetry. They should not embed engineering conclusions merely because a metric can be derived during collection.

Engineering Intelligence operates on collected evidence and may use deterministic rules, statistical analysis, machine learning, correlation, provider-specific engineering logic, and AI-assisted analysis.

The intended engineering flow is:

**Evidence → Analysis → Finding → Recommendation → Proposed Action**

AI is not mandatory for analysis that can be performed more reliably by deterministic or statistical techniques. Collected evidence remains the source of truth.

The PostgreSQL provider currently implements the functional collector baseline through PG-008 — Session & Connection Activity. Engineering Intelligence is the next higher-level foundation that will be developed on top of the evidence repository.

## AI Engineering Assistant

Keystone includes an AI Engineering Assistant concept that spans Engineering Intelligence and Presentation.

The Assistant is intended to provide natural-language interaction with Keystone evidence, history, findings, recommendations, and engineering context. It may explain, summarize, compare, correlate, and assist interactive analysis.

The Assistant is not an autonomous remediation engine and does not independently make production changes.

A separate future concept, **Keystone AI Agents**, covers autonomous read-only diagnostic investigation and is intentionally outside the current Keystone product scope.

## Human-Controlled Actions

Keystone may generate recommendations, scripts, commands, or future user-initiated execution controls.

State-changing actions must remain behind an explicit human decision boundary. Keystone does not autonomously remediate production environments.

## Principle

**Shared platform core, provider-specific database knowledge, evidence-backed engineering intelligence, and human-controlled action.**

Keystone should introduce abstractions when they solve repeated engineering problems, not in anticipation of hypothetical future requirements.
