# ADR-0013 — Finding-Driven Notification

**Status:** Approved  
**Date:** 2026-10-05  
**Clarifies:** ADR-0005 — Keystone Scope

## Context

Keystone is intended to run unattended in customer environments during long-term DBA engagements. In that mode nobody should have to run assessments repeatedly and inspect the results to discover that something needs attention. Keystone must tell the engineer.

ADR-0005 states that Keystone is not a general-purpose monitoring platform and that generic alerting is not a primary goal. A notification capability therefore needs a clear boundary so that it does not turn Keystone into a metric-threshold alerting system.

## Decision

Keystone notifies on **engineering findings**, not on raw metrics.

A notification is triggered by a change in Keystone's engineering conclusions, for example:

- a new Finding is detected,
- an existing Finding escalates in severity (for example WARNING → CRITICAL),
- a Finding is resolved,
- an assessment can no longer be performed because required evidence is missing or stale.

Raw telemetry such as CPU, memory or connection counts may still be collected as evidence and may contribute to Findings. A metric crossing a value is never a notification trigger by itself; it becomes relevant only through a Finding produced by Engineering Intelligence.

Keystone complements monitoring platforms such as Zabbix or Prometheus rather than replacing their metric alerting.

## Consequences

- Notifications carry engineering meaning: what was found, why it matters and what to do, with links to evidence and recommendations.
- Continuous operation requires a Finding lifecycle (new, ongoing, escalated, resolved). Without it every scheduled run would re-report the same condition.
- Missing or stale evidence must be visible as its own state, otherwise silence could be mistaken for health.
- Notification channels (e-mail, chat, ticketing) are an implementation detail and can be added without changing this decision.
- Metric dashboards and threshold alerting remain out of scope, consistent with ADR-0005.
