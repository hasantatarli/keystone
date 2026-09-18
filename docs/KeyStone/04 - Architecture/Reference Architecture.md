# Keystone Reference Architecture

**Status:** Current  
**Version:** 0.2  
**Last Updated:** 2026-09-18

## Purpose

Keystone is a provider-agnostic database engineering platform designed to collect technical facts from database environments, preserve them centrally, transform them into engineering findings and recommendations, and present those results to users for human-controlled action.

The architecture separates evidence collection, engineering interpretation, and user-facing presentation.

## Architectural Model

Keystone is organized around three main layers:

### 1. Automation

**Collection → Scheduling → Execution → Repository**

The Automation layer is responsible for continuously and reliably producing engineering evidence with minimal human intervention.

- **Collection** defines and gathers observable database facts.
- **Scheduling** determines when assigned collectors should run.
- **Execution** reliably runs collectors through the queue/worker model.
- **Repository** stores platform state, execution history, provider telemetry, and historical evidence.

The repository is the system of record for collected engineering evidence.

### 2. Engineering Intelligence

Engineering Intelligence transforms evidence into engineering meaning.

It may combine:

- deterministic engineering rules,
- statistical analysis,
- machine-learning techniques,
- correlation,
- provider-specific engineering logic,
- AI-assisted analysis where it adds value.

The primary outputs are **Findings** and **Recommendations**.

AI is not required for conclusions that can be produced more reliably by deterministic or statistical methods. AI may contribute to contextual reasoning and correlation, but collected evidence remains the source of truth and AI is not the sole source of engineering decisions.

### 3. Presentation and Action

The Presentation layer exposes engineering outputs to users through reports and future interactive interfaces.

Typical outputs include:

- findings,
- supporting evidence,
- recommendations,
- proposed actions,
- generated scripts or commands where appropriate.

Keystone does not autonomously remediate production environments. It may propose an action, prepare a script, or provide a user-initiated execution mechanism, but the decision to perform a change remains with the user.

## AI Engineering Assistant

The **AI Engineering Assistant** is a cross-cutting Keystone capability spanning Engineering Intelligence and Presentation rather than a standalone pipeline stage.

It is intended to let users interact naturally with Keystone's evidence, history, findings, recommendations, and engineering context.

Representative interactions include:

- What became worse in this PostgreSQL environment during the last month?
- Why does replication lag repeatedly?
- Why is this finding Critical?
- What changed on a table during the last three months?
- Which risks should be addressed before a database upgrade?

The Assistant may explain, summarize, compare, correlate, and reason over Keystone evidence and engineering outputs. Its answers should remain evidence-backed and traceable where practical.

Autonomous target-side diagnostic investigation is not part of the AI Engineering Assistant. A separate **Keystone AI Agents** concept has been identified for future exploration and is not part of the current Keystone product scope.

## Provider Architecture

Database-specific behavior is implemented through providers.

The Keystone core owns generic concepts such as targets, connections, collector definitions, assignments, scheduling/orchestration, queueing, execution history, and credential handling.

Each provider owns its database-specific collectors, repository objects, migrations, persistence logic, and provider-specific engineering knowledge where appropriate.

The initial provider is PostgreSQL. The architecture is intended to support additional providers such as SQL Server, MySQL, MongoDB, and other database technologies without changing the core execution model.

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

Collector assignments determine which collectors run against which targets. Scheduling will determine when recurring assignments become eligible for execution.

Execution requests are placed into a central queue. Workers claim eligible tasks, execute the appropriate collector, persist the results, and record execution history.

The worker model supports parallel execution, task ownership, heartbeat-based liveness detection, stale-task recovery, and bounded retries.

Database-scoped execution uses best-effort fan-out: an individual database failure does not prevent successful databases from being collected. Partial execution is represented explicitly rather than hidden as success.

## Repository Model

The central repository separates generic Keystone metadata from provider-specific telemetry.

- The **`keystone` schema** contains platform metadata and execution control data.
- Provider schemas, such as **`postgresql`**, contain provider-specific inventory and telemetry.

Repository data is intentionally separated into current-state and historical snapshot models depending on the nature of the collector.

## Collection and Interpretation Boundary

Collectors are responsible for collecting observable facts from the target environment.

They should not embed conclusions such as risk level, health score, growth classification, root cause, or remediation advice unless the value itself is a direct database fact.

Interpretation belongs to Engineering Intelligence.

This preserves the reusable flow:

**Evidence → Analysis → Finding → Recommendation → Proposed Action**

The same evidence can therefore support multiple customer-facing capabilities without duplicating collection logic.

## Human Decision Boundary

Keystone may analyze, recommend, explain, and prepare proposed remediation.

It must not independently decide to change a production database environment.

Any state-changing operational action remains behind an explicit human decision boundary. Future user-initiated execution may be supported, but it must be distinguishable from autonomous remediation and auditable.

## UI and API

UI and API are cross-cutting interaction mechanisms rather than architectural pipeline stages.

Over time they may expose capabilities across all three layers, including target management, collector assignment, scheduling, execution history, findings, recommendations, reports, AI Assistant interaction, and user-controlled actions.

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

- Provider-agnostic core, provider-specific database knowledge.
- Automation, Engineering Intelligence, and Presentation are separate architectural concerns.
- Target topology and collector execution scope are separate concepts.
- Databases are execution units, not Keystone targets.
- Collect facts before interpreting them.
- Evidence is the source of truth.
- Use deterministic or statistical methods where they are more reliable than AI.
- AI augments engineering analysis and user interaction; it does not replace evidence.
- Keep provider telemetry separate from platform metadata.
- Preserve execution history and failure visibility.
- Keystone does not autonomously remediate production environments.
- UI and API may span the platform rather than belonging to a single layer.
- Introduce abstractions when repeated implementation needs justify them.
- Keep the architecture simple enough to evolve from real customer requirements.
