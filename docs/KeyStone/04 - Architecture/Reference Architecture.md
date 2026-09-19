# Keystone Reference Architecture

**Status:** Current  
**Version:** 0.3  
**Last Updated:** 2026-09-19

## Purpose

Keystone is a provider-agnostic database engineering platform designed to collect technical facts from database environments, preserve them centrally, transform them into engineering findings and recommendations, and present those results to users for human-controlled action.

The architecture separates evidence collection, engineering interpretation, and user-facing presentation.

## Architectural Model

Keystone is organized around three main layers:

### 1. Automation

**Collection → Scheduling → Execution → Repository**

The Automation layer is responsible for reliably producing engineering evidence with minimal human intervention. Collection may be continuous, assessment-driven, or explicitly requested by a user.

Its current logical module boundaries are:

- **Target Management** — systems, nodes, connections, credentials, and provider association.
- **Collector Framework** — collector definitions, discovery/registration, execution scope, assignments, and provider collectors.
- **Scheduler** — recurring policies, frequencies, eligibility, and queue creation.
- **Execution Engine** — queueing, workers, claiming, credentials, DATABASE fan-out, retries, timeout handling, heartbeat, recovery, and run history.
- **Evidence Repository** — current state, historical snapshots, provider telemetry, and evidence access.

Scheduling is one source of collection requests, not the only source. Snapshot assessment runs and explicit user requests may also request approved collectors through the same Execution Engine.

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

Engineering Intelligence is an asynchronous processing pipeline. New evidence can trigger analysis independently from the user interface, and reusable analysis results are persisted rather than recomputed whenever a screen is opened.

The engineering model distinguishes:

- **Raw Evidence** — observable facts collected from target environments.
- **Derived Evidence** — reusable calculations, trends, correlations, and other analytical results derived from raw evidence.
- **Assessment Results** — the outcome of an engineering assessment: assessed and healthy, attention required, or not assessed / insufficient evidence.
- **Findings** — engineering conditions, problems, or risks requiring attention.
- **Root Cause Analysis (RCA)** — hypotheses evaluated using supporting, contradicting, and missing evidence.
- **Recommendations** — one or more possible engineering responses to a finding.
- **Proposed Actions** — reusable operational steps that may later support a recommendation, always behind the human decision boundary.

Finding confidence, root-cause confidence, and recommendation confidence are separate concepts. Confidence must be grounded in evidence coverage, evidence quality, hypothesis support, contradicting evidence, and historical consistency rather than an ungrounded AI-generated percentage.

A healthy assessment is a first-class result. Zero findings must never be treated as proof that everything is healthy when required evidence was not collected.

AI is not required for conclusions that can be produced more reliably by deterministic or statistical methods. AI may contribute to contextual reasoning and correlation, but collected evidence remains the source of truth and AI is not the sole source of engineering decisions.

### Keystone Dictionary

The **Keystone Dictionary** is the engineering knowledge base used by Engineering Intelligence and the AI Engineering Assistant.

It may contain engineering concepts, assessment definitions, analysis definitions, finding definitions, RCA models, evidence requirements, hypotheses, recommendation definitions, and reusable action definitions.

Provider-specific knowledge remains provider-specific. For example, PostgreSQL dead tuple and transaction-ID wraparound knowledge belongs to the PostgreSQL provider. Generic concepts such as capacity risk may be shared by multiple providers while each provider supplies its own detection and analysis logic.

Dictionary definitions are distinct from customer/runtime instances. The Dictionary describes what Keystone knows; the repository records what Keystone observed or concluded about a specific environment.

RCA definitions should describe the evidence required to investigate likely causes, not only the minimum evidence required to detect a finding. Missing required evidence is itself visible as an evidence gap. AI may suggest additional hypotheses outside the predefined model, but such suggestions must remain distinguishable from Dictionary-defined engineering knowledge.

### 3. Presentation

The current design focus is Presentation. Action execution is intentionally deferred until the engineering presentation experience is established.

Presentation is an engineering workspace rather than only a monitoring dashboard or report viewer. Its primary views are:

- **Estate Overview** — what needs attention across managed environments.
- **System Engineering View** — the engineering state, assessment coverage, healthy areas, findings, and unassessed areas for one system.
- **Finding / Investigation Workspace** — finding details, evidence, RCA hypotheses, supporting and contradicting evidence, missing evidence, recommendations, and contextual AI interaction.
- **Change & History Explorer** — configuration, workload, capacity, topology, behavior, and finding changes over time.

Presentation should emphasize engineering meaning rather than raw metric dashboards. Raw evidence remains available for inspection where useful.

Action remains a later concern. The existing human decision boundary still applies to any future state-changing capability.

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

The Assistant should preferentially ground its reasoning in actual Keystone evidence, derived evidence, findings, Dictionary knowledge, and historical context. General model knowledge may supplement these sources when appropriate, but it must not silently replace missing evidence.

The Assistant may reason over predefined RCA hypotheses, explain why a hypothesis is supported, identify contradicting or missing evidence, and suggest additional investigation paths. It must not invent unavailable telemetry.

Autonomous target-side diagnostic investigation is not part of the AI Engineering Assistant. Main Keystone may allow a user to request an existing approved collector to obtain fresh evidence. A separate **Keystone AI Agents** concept covers autonomous target-side investigation and is not part of the current Keystone product scope.

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

Logically, the repository also distinguishes:

- **Platform Repository** — targets, collectors, schedules, executions, and runtime state.
- **Evidence Repository** — raw current-state and historical evidence.
- **Intelligence Repository** — reusable derived evidence, assessment results, findings and finding history, RCA results, and recommendations.

These are logical responsibilities and do not require separate physical databases.

## Collection and Interpretation Boundary

Collectors are responsible for collecting observable facts from the target environment.

They should not embed conclusions such as risk level, health score, growth classification, root cause, or remediation advice unless the value itself is a direct database fact.

Interpretation belongs to Engineering Intelligence.

This preserves the reusable flow:

**Evidence → Derived Evidence → Assessment → Finding → RCA → Recommendation → Proposed Action**

Not every assessment produces a finding. An assessment may explicitly conclude that the assessed area is healthy or that evidence is insufficient.

The same evidence can therefore support multiple customer-facing capabilities without duplicating collection logic.

## Assessment Operating Modes

Keystone uses the same collection, Dictionary, analysis, assessment, finding, RCA, and recommendation foundations in multiple operating modes.

- **Snapshot Assessment** — point-in-time collection for one-off health checks or similar assessments.
- **Temporary Observation** — collection over a bounded period such as 24 hours or seven days when trends and workload behavior are needed.
- **Continuous Engineering** — recurring collection, historical analysis, change detection, and continuously updated assessments.

An **Assessment Profile** defines the assessment purpose and therefore the assessment definitions, evidence requirements, and collector coverage required for a run. Examples may include PostgreSQL Health Check, Upgrade Readiness, HA/DR Assessment, Security Assessment, or Performance Baseline.

Snapshot assessments must clearly expose historical evidence that cannot be assessed from point-in-time data. One-off Health Check and Continuous Engineering are therefore operating modes over the same engineering platform rather than separate analysis products.

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
- Healthy, attention-required, and insufficient-evidence assessment outcomes are explicitly distinguishable.
- Collect enough evidence not only to detect important conditions but, where practical, to investigate their likely causes.
- Missing evidence must remain visible rather than being filled by inference.
- Keystone Dictionary definitions and runtime/customer results are separate concerns.
- Use deterministic or statistical methods where they are more reliable than AI.
- AI augments engineering analysis and user interaction; it does not replace evidence.
- Keep provider telemetry separate from platform metadata.
- Preserve execution history and failure visibility.
- Keystone does not autonomously remediate production environments.
- UI and API may span the platform rather than belonging to a single layer.
- Introduce abstractions when repeated implementation needs justify them.
- Keep the architecture simple enough to evolve from real customer requirements.
