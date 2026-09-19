# ADR-0012 — AI Engineering Assistant Role

**Status:** Approved  
**Date:** 2026-09-18  
**Amended:** 2026-09-19

## Context

Keystone is being developed as an AI-supported database engineering platform, but AI should not replace deterministic engineering logic or become the source of collected technical facts.

At the same time, limiting AI to rewriting completed findings into natural language would leave much of its engineering value unused.

Keystone needs a clear boundary for AI that makes it visible and valuable to users while preserving evidence-based engineering.

## Decision

Keystone will include an **AI Engineering Assistant** as a cross-cutting capability spanning **Engineering Intelligence** and **Presentation**.

The Assistant is not a separate pipeline stage.

Within Engineering Intelligence, AI may assist with contextual reasoning, correlation, comparison, summarization of complex evidence, and other analysis where language-model capabilities add value.

Within Presentation, the Assistant provides a natural-language interface to Keystone's evidence, derived evidence, history, assessments, findings, RCA results, recommendations, Keystone Dictionary knowledge, and engineering context.

Representative interactions include:

- identifying what became worse over a selected period,
- explaining why a finding has a given severity,
- exploring relationships between findings and historical evidence,
- explaining recurring replication lag using available evidence,
- describing how a database object changed over time,
- discussing risks relevant to an upgrade or engineering decision.

Deterministic rules, statistical analysis, machine learning, correlation, and provider-specific engineering logic remain first-class mechanisms. AI is not mandatory where another method is more reliable.

Collected evidence remains the source of truth. AI-generated explanations and reasoning should be evidence-backed and traceable where practical.

The Assistant should prefer, in order of engineering authority, actual Keystone evidence and derived evidence, persisted findings/RCA, Keystone Dictionary knowledge, and historical Keystone context before supplementing with general model knowledge.

The Keystone Dictionary defines provider-aware engineering knowledge such as assessment definitions, finding definitions, RCA evidence requirements, standard hypotheses, recommendations, and related engineering concepts. The Assistant may reason over this knowledge and may suggest additional hypotheses when the predefined model does not fully explain the evidence.

AI-suggested hypotheses must remain distinguishable from Dictionary-defined hypotheses. Missing evidence must not be filled by model inference or presented as observed fact.

The Assistant may identify what additional evidence would increase RCA confidence. Main Keystone may allow a user to request an existing approved collector to obtain such evidence; this is different from allowing the AI to autonomously invent and execute target-side diagnostic SQL.

The AI Engineering Assistant does not autonomously run unrestricted diagnostics against target environments and does not autonomously remediate production environments.

## Separate AI Agents Concept

Autonomous read-only investigation that can actively request or execute approved target-side diagnostics is a separate future product concept named **Keystone AI Agents**.

Keystone AI Agents are not part of the current Keystone product scope or V1 commitment.

## Consequences

- AI remains visible in the product without becoming the foundation of factual correctness.
- Users can interact conversationally with Keystone engineering knowledge.
- AI explanations can expose supporting, contradicting, and missing evidence rather than only presenting a conclusion.
- Dictionary-defined and AI-suggested hypotheses remain distinguishable.
- AI does not compensate for missing telemetry by inventing evidence.
- Existing deterministic and statistical analysis remains independently testable.
- AI can add contextual reasoning and correlation where appropriate.
- The main Keystone product retains a lower security risk than an autonomous diagnostic agent.
- Future AI Agents can evolve separately with stronger security, permission, audit, and testing requirements.
