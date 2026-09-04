# ADR-0010 — Collection and Interpretation Separation

**Status:** Approved  
**Date:** 2026-09-04

## Context

Database telemetry can often be interpreted at collection time, but embedding health rules and recommendations directly into collectors couples evidence gathering to current diagnostic assumptions.

The same raw evidence may later support health assessments, performance investigations, trend analysis, customer-specific policies, or automated actions.

## Decision

Keystone separates factual collection from engineering interpretation.

The intended capability pipeline is:

**Collection → Finding → Recommendation → Action**

Collectors gather facts and persist evidence. Findings evaluate that evidence. Recommendations explain appropriate responses. Actions may later execute approved operational changes.

AI-assisted capabilities may use this engineering layer, but deterministic evidence and rules remain independent from AI-generated interpretation.

## Consequences

- Collected telemetry remains reusable across multiple capabilities.
- Finding logic can evolve without rewriting collectors or historical evidence.
- Recommendations and future automation can be reviewed independently from data collection.
- Provider collectors remain focused on database facts rather than product policy.
- Keystone can introduce AI without making AI the sole source of engineering decisions.