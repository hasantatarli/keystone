# ADR-0009 — Target Topology and Collector Execution Scope

**Status:** Approved  
**Date:** 2026-09-04

## Context

Collectors operate at different levels. Some facts belong to a database system, some to an individual node, and others require execution inside every database.

Representing every database as a Keystone target would make target topology mirror dynamic database inventory and would couple infrastructure modeling to collector behavior.

## Decision

Keystone separates **target topology** from **collector execution scope**.

Target topology uses:

- `SYSTEM`
- `NODE`

Collector execution scope uses:

- `SYSTEM`
- `NODE`
- `DATABASE`

`DATABASE` is an execution scope, not a target type.

Database-scoped collectors are assigned to a SYSTEM target and fan out across databases discovered at execution time.

## Consequences

- Target topology represents stable database infrastructure rather than every database resource.
- Databases can appear or disappear without target-management churn.
- The worker can choose execution behavior from collector metadata instead of collector-specific code paths.
- Cluster-wide collection can occur once at SYSTEM level while node-specific collection remains available through NODE targets.
- Database inventory and database-scoped telemetry remain separate concerns.