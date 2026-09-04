# ADR-0004 — Use-Case Driven Development

**Status:** Approved

## Context

Keystone can accumulate technical features quickly because database platforms expose many metrics, views, and automation opportunities.

Building capabilities simply because the underlying technology makes them possible would risk producing a large but unfocused framework.

## Decision

Keystone will be developed **use-case first, not feature first**.

New collectors, findings, recommendations, and actions should be justified by a concrete engineering problem, service requirement, or repeated operational need.

Technical abstractions should emerge from repeated implementation needs rather than from hypothetical future scenarios.

## Consequences

- Development remains aligned with real consulting and customer problems.
- Collector growth is prioritized by engineering value rather than metric availability.
- Features without a clear use case can be deferred even when technically easy to implement.
- The platform can evolve incrementally without committing early to unnecessary abstractions.