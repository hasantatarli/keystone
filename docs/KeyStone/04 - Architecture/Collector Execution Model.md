# Collector Execution Model

## Purpose

This document describes how Keystone maps database topology to collector execution without coupling individual collectors to the worker implementation.

## Target Topology

Keystone models database infrastructure using two target types:

- **SYSTEM** — a logical database system, such as a standalone PostgreSQL instance or a PostgreSQL cluster.
- **NODE** — an individual physical or virtual database node when node-specific collection is required.

Databases are not modeled as Keystone targets. They remain resources discovered within a database system.

This keeps topology stable while allowing databases to be created and removed without continuously changing the target hierarchy.

## Collector Definitions

A collector definition identifies a collection capability independently from its assignments and execution history.

Collectors use a stable collector key rather than environment-specific numeric identifiers. Their metadata also declares an execution scope so the worker can choose the correct execution behavior without hardcoding individual collector names.

The supported execution scopes are:

| Scope | Meaning |
| --- | --- |
| `SYSTEM` | Execute once against the logical database system connection. |
| `NODE` | Execute against the assigned node. |
| `DATABASE` | Discover databases from the assigned system and execute separately inside each database. |

Target type and execution scope are related but deliberately separate concepts.

## Assignments

A collector assignment connects a collector definition to a target and controls whether that collection capability should execute for that target.

Assignments represent configuration. Queue tasks represent individual executions. Keeping these concepts separate allows the same assignment to produce many historical runs without duplicating configuration.

## Database-Scoped Fan-Out

DATABASE-scoped collectors are assigned to a SYSTEM target rather than creating one Keystone target per database.

At execution time Keystone:

1. Connects through the SYSTEM target connection.
2. Discovers the currently connectable databases.
3. Opens a database-specific connection for each discovered database.
4. Executes the same collector independently in each database.
5. Combines the collected rows into one logical collector run.

A shared capture timestamp is used across the fan-out so rows from the same logical execution can be compared as one snapshot.

Database discovery is performed at execution time. Historical database inventory is useful evidence, but it is not used as the runtime execution list because it may be stale.

## Partial Execution

Database fan-out is best-effort. Failure in one database does not prevent collection from continuing against the remaining databases.

The logical run is classified as:

- **SUCCESS** when all intended database executions succeed.
- **PARTIAL_SUCCESS** when at least one database succeeds and at least one fails.
- **FAILED** when no database execution succeeds.

A successfully queried database still counts as successful when the collector legitimately returns zero rows.

## Queue and Worker Flow

The runtime flow is intentionally generic:

**Assignment → Queue → Worker → Collector → Provider Repository → Run History**

Workers claim eligible tasks, validate the registered collector, execute according to its declared scope, persist provider-specific results, and record the execution outcome.

Running tasks maintain liveness information so abandoned executions can be detected and recovered. Recovery is bounded to prevent permanently failing work from cycling indefinitely.

Task ownership is protected during execution and finalization so two workers cannot legitimately complete the same active task.

## Result Persistence

Execution orchestration is generic, while result persistence remains collector/provider specific because different collectors produce different data structures.

Stable collector keys are used to route collected results to the appropriate provider persistence logic. Numeric repository IDs are not treated as portable collector identities.

## Collection Boundary

Collectors collect facts. Execution scope determines where those facts must be collected.

Neither topology nor collector execution should contain finding or recommendation logic. Interpretation belongs to higher layers of Keystone so the same collected evidence can support health checks, trend analysis, recommendations, and future automated actions.

## Design Principles

- Model stable infrastructure as targets; discover dynamic databases at runtime.
- Keep target topology separate from collector execution scope.
- Drive worker behavior from collector metadata, not collector-specific branching.
- Treat a multi-database execution as one logical snapshot.
- Allow partial database collection without hiding failures.
- Keep collection separate from interpretation.