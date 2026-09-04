# ADR-0005 — Keystone Scope

**Status:** Approved

## Context

Keystone collects technical telemetry and may eventually provide continuous analysis, but its purpose is broader than traditional infrastructure monitoring.

Monitoring platforms are optimized for observing current state, alerting, dashboards, and operational visibility. Keystone is intended to capture database engineering knowledge and turn evidence into reusable engineering outcomes.

## Decision

Keystone is **not positioned as a general-purpose monitoring platform**.

It may collect its own telemetry and consume information from monitoring systems, but that evidence exists to support engineering capabilities such as assessments, findings, recommendations, investigations, and controlled operational workflows.

Keystone should complement existing monitoring tools rather than reproduce every monitoring feature.

## Consequences

- Real-time dashboards and generic alerting are not primary product goals.
- Historical telemetry is collected where it supports engineering analysis and decision-making.
- Integration with existing monitoring systems remains valid where they already provide useful evidence.
- Product scope is driven by database engineering outcomes rather than monitoring feature parity.