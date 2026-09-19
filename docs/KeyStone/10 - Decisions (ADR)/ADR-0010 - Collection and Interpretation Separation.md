# ADR-0010 — Collection and Interpretation Separation

**Status:** Approved  
**Date:** 2026-09-04  
**Amended:** 2026-09-18, 2026-09-19

## Context

Database telemetry can often be interpreted at collection time, but embedding health rules and recommendations directly into collectors couples evidence gathering to current diagnostic assumptions.

The same raw evidence may later support health assessments, performance investigations, trend analysis, customer-specific policies, AI-assisted analysis, or proposed operational actions.

## Decision

Keystone separates factual collection from engineering interpretation.

Collectors gather observable facts and persist evidence. Interpretation is performed by Engineering Intelligence after collection.

The intended engineering flow is:

**Raw Evidence → Derived Evidence → Assessment → Finding → RCA → Recommendation → Proposed Action**

Derived evidence that is useful across requests is persisted so historical telemetry does not need to be fully reprocessed whenever a user opens a screen or requests analysis.

An assessment does not necessarily produce a finding. It may conclude that an area was assessed and healthy, that attention is required, or that evidence is insufficient.

Engineering Intelligence may combine deterministic rules, statistical analysis, machine learning, correlation, provider-specific engineering logic, and AI-assisted analysis.

AI is not required where deterministic or statistical methods provide a more reliable result. Collected evidence remains the source of truth, and AI must not become the sole source of engineering decisions.

Findings describe identified engineering conditions or risks.

RCA is distinct from finding detection. RCA evaluates possible causes using supporting evidence, contradicting evidence, missing evidence, and evidence-grounded confidence. Collector design should therefore consider the evidence required to investigate important findings, not only the minimum evidence required to detect them.

Recommendations describe appropriate responses. A finding may have multiple recommendations. Recommendations may contain ordered steps and may reuse Proposed Action definitions. Proposed Actions may provide scripts, commands, or other remediation guidance.

Finding confidence, root-cause confidence, and recommendation confidence are separate concerns and must not be represented by ungrounded AI-generated certainty.

## Human Decision Boundary

Keystone does not autonomously remediate production environments.

Any state-changing action remains behind an explicit human decision boundary. Keystone may prepare a proposed action or support future user-initiated execution, but the user decides whether the change is performed.

## Consequences

- Collected telemetry remains reusable across multiple capabilities.
- Finding logic can evolve without rewriting collectors or historical evidence.
- Reusable derived evidence and engineering results can be persisted and analyzed incrementally.
- Healthy and insufficient-evidence assessment outcomes remain visible even when no finding exists.
- RCA can explicitly expose missing evidence and alternative hypotheses.
- A finding can have multiple recommendations, including ordered multi-step recommendations.
- Deterministic, statistical, ML, and AI-assisted methods can coexist.
- Recommendations and proposed actions can be reviewed independently from data collection.
- Provider collectors remain focused on database facts rather than product policy.
- Keystone can use AI prominently without making AI the source of truth.
- Production remediation remains human-controlled.
