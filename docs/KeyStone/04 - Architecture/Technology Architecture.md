# Technology Architecture

**Status:** Current  
**Version:** 0.3  
**Project:** Keystone  
**Last Updated:** 2026-09-19

## Architectural Direction

Keystone is a provider-oriented database engineering platform with a shared execution and repository core.

The platform is organized conceptually into three layers:

1. **Automation** — Target Management, Collector Framework, Scheduling, Execution, and Evidence Repository
2. **Engineering Intelligence** — asynchronous analysis, derived evidence, assessments, findings, RCA, recommendations, and the Keystone Dictionary
3. **Presentation** — estate/system engineering views, investigation workspace, history/change exploration, reporting, and contextual AI interaction

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

Repository telemetry is stored as current state or historical snapshots according to the nature of the evidence.

At the logical level Keystone distinguishes:

- **Platform state** — targets, definitions, schedules, queue/execution state, and history.
- **Raw evidence** — observable target facts.
- **Intelligence state** — derived evidence, assessment results, findings/history, RCA results, and recommendations.

These are logical boundaries and may remain in the same physical PostgreSQL repository.

Persisting reusable intelligence results allows Keystone to analyze incrementally and avoids repeatedly reprocessing years of historical telemetry when a user opens a screen or asks a question.

## Execution Technology

Collectors are registered as definitions and assigned to targets. Executions are coordinated through the Keystone collection queue and processed by workers.

Scheduling is a distinct Automation responsibility: it determines when recurring assignments should produce execution requests. The continuously running scheduler implementation remains future work.

The Scheduler is not the only execution initiator. Snapshot Assessment Runs, bounded observation runs, and explicit user requests may also submit approved collection work to the same Execution Engine.

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

**Raw Evidence → Derived Evidence → Assessment → Finding → RCA → Recommendation → Proposed Action**

Engineering analysis runs independently from Presentation. New evidence may trigger asynchronous analysis and persisted intelligence results.

Assessment results explicitly distinguish:

- assessed and healthy,
- attention required,
- not assessed / insufficient evidence.

Findings represent attention-requiring engineering conditions and are not used to create artificial positive findings for healthy checks.

RCA evaluates predefined and, where appropriate, AI-suggested hypotheses using supporting evidence, contradicting evidence, missing evidence, and evidence-grounded confidence. Missing evidence is preserved as an explicit engineering state rather than inferred away.

AI is not mandatory for analysis that can be performed more reliably by deterministic or statistical techniques. Collected evidence remains the source of truth.

The PostgreSQL provider currently implements the functional collector baseline through PG-008 — Session & Connection Activity. Engineering Intelligence is the next higher-level foundation that will be developed on top of the evidence repository.

## Keystone Dictionary

The Keystone Dictionary is the engineering knowledge base consumed by analysis, assessment, RCA, recommendations, and the AI Engineering Assistant.

It may define generic engineering concepts plus provider-specific assessment definitions, analyses, findings, RCA evidence checklists, hypotheses, recommendations, and reusable action definitions.

Provider knowledge remains provider-specific. Generic concepts may group comparable concerns across providers, while detection and RCA logic can remain native to PostgreSQL, SQL Server, MySQL, MongoDB, or another provider.

Dictionary definitions are separate from runtime instances stored for customer systems.

Collector coverage should be designed from engineering requirements backward: **Assessment → Finding → RCA hypotheses → Required Evidence → Collector coverage**. This allows collector gaps to be identified from missing RCA evidence rather than from an arbitrary target collector count.

## AI Engineering Assistant

Keystone includes an AI Engineering Assistant concept that spans Engineering Intelligence and Presentation.

The Assistant is intended to provide natural-language interaction with Keystone evidence, derived evidence, history, assessments, findings, RCA, recommendations, Dictionary knowledge, and engineering context. It may explain, summarize, compare, correlate, and assist interactive analysis.

It should reason from Keystone evidence and Dictionary knowledge before relying on general model knowledge. It may identify missing evidence and suggest additional hypotheses, but it must not present unavailable telemetry as fact.

The Assistant is not an autonomous remediation engine and does not independently make production changes.

A separate future concept, **Keystone AI Agents**, covers autonomous read-only diagnostic investigation and is intentionally outside the current Keystone product scope.

## Assessment Operating Modes

The same technical platform supports multiple evidence acquisition modes:

- **Snapshot Assessment** for point-in-time Health Checks and similar engagements.
- **Temporary Observation** for bounded collection windows when historical behavior is needed.
- **Continuous Engineering** for recurring evidence collection and continuously updated engineering assessments.

Assessment Profiles define the assessment purpose, required engineering checks, evidence requirements, and therefore the collector bundle needed for a run. This allows one-off Health Assessment and continuous Keystone operation to reuse the same Engineering Intelligence model while clearly exposing evidence that cannot be assessed without history.

## Presentation Model

Presentation is designed as an engineering workspace rather than a raw telemetry dashboard. The initial conceptual views are Estate Overview, System Engineering View, Finding / Investigation Workspace, and Change & History Explorer.

Action execution is intentionally deferred until the Presentation and engineering investigation experience is established. The human decision boundary remains unchanged.

## Human-Controlled Actions

Keystone may generate recommendations, scripts, commands, or future user-initiated execution controls.

State-changing actions must remain behind an explicit human decision boundary. Keystone does not autonomously remediate production environments.

## Principle

**Shared platform core, provider-specific database knowledge, evidence-backed engineering intelligence, and human-controlled action.**

Keystone should introduce abstractions when they solve repeated engineering problems, not in anticipation of hypothetical future requirements.
