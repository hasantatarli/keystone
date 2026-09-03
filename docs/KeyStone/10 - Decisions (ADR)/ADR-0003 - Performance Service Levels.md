**Status:** Approved
**Date:** 2026-08-04

## Context

Performance-related observations may appear during a general database Health Assessment. However, identifying the root cause of a specific performance problem requires a deeper and problem-driven engineering investigation.

Combining these two activities under a single service would create unclear scope, unpredictable delivery expectations, and misleading customer outcomes.

## Decision

Keystone separates performance work into two service levels:

1. **Health Assessment**
   - Reviews high-level performance indicators.
   - Identifies risks and areas requiring further investigation.
   - Does not guarantee root cause identification.

2. **Performance Investigation**
   - Investigates a specific reported performance problem.
   - Performs detailed analysis across database, infrastructure, and application interaction.
   - Aims to identify the root cause and provide evidence-based recommendations.

Remediation is treated as an optional follow-up activity after root cause identification.

## Consequences

- Health Assessment remains predictable and bounded.
- Performance Investigation may have variable duration.
- Customers can purchase diagnosis without purchasing remediation.
- Problems outside the database layer can be identified and documented without forcing DataWiser to own unrelated implementation work.
- Reports must clearly distinguish observations, suspected causes, confirmed root causes, and recommended actions.