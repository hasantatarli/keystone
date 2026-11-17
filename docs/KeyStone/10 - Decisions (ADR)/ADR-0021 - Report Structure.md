# ADR-0021 — Report Structure

**Status:** Approved (Hasan, 2026-11-16)  
**Date:** 2026-11-16

## Context

The health check report (hc128, 2026-11-14) is complete and honest, but long: every finding's text appears in up to five places (key findings, affected areas, topic summary, findings, check results), and the executive tab carries technical text such as the sudoers line for pg_wal. The pilot feedback was "I found nothing to tell me what to do, what happened, what the impact is". Hasan collected format reviews from three other AI assistants (Kimi, DeepSeek, ChatGPT) reading the report as a customer CEO, CTO and IT manager, with a design each, and a real consultant report (DSP, 2024) as an example; none of these is kept in the repository.

They agree on: write each finding once in full and let summaries point to it; no paragraphs for executives; separate collection success (39/39) from assessment coverage (47/52); one panel for what could not be assessed; a prioritized action list; related findings told as one event (failover and restarts); healthy checks folded; only changed settings up front; keep rule ids, evidence time and the meaning / causes / impact / recommendation structure. The consultant report adds a short prose summary, explicit "no concern" statements and one closing list of recommendations.

## Decision

| # | Topic | Decision |
| --- | --- | --- |
| 1 | One report, three tabs | One report; sections answer questions, not job titles (a small company's IT manager reads all three): **1. Executive Summary** — where do we stand; **2. Engineering View** — where, and in which order; **3. Findings and Evidence** — what to do and how to verify. |
| 2 | Format | Three tabs on screen, as the two tabs today (Hasan): Executive Summary, Engineering View, Findings and Evidence. Printed or saved as PDF, all three come one after another, each on a new page, folded parts open — as the current report already does with its two tabs. |
| 3 | Write once | A finding's full text (meaning, causes, impact, recommendation, evidence) appears only in section 3. Sections 1 and 2 give one line and a link. The same holds for "not assessed" texts: one short line in the summary, the full way to allow it in section 3. |
| 4 | No score | No composite health or risk score: its weights would be our invention and could not be defended ("by what, for whom"). The summary shows counts by severity, coverage and the affected areas. |
| 5 | Two measures | Collection success (collector runs) and assessment coverage (checks that could be judged, of those applicable) are shown separately with their own names. |
| 6 | Executive Summary | Three or four sentences of plain prose (what was found, what to do, what is not needed); counts by severity; the two measures; the affected-areas matrix; areas with no concern named as such; decisions the customer must take only where a rule marks its recommendation as a decision (for example whether point-in-time recovery is needed). No technical text, no invented owners, dates or costs. |
| 7 | Engineering View | Action table in the suggested review order (finding, where, next step, cost of the fix); events told once on a timeline (failover, restarts); a "missing evidence" panel in three kinds: needs a permission or setting (the customer can act), needs time (opens when Keystone collects regularly), needs workload (may never open: the system is too lightly used to measure; not a gap). No coverage target is promised. Configuration changes only, the rest folded. |
| 8 | Findings and Evidence | Each finding once: visible — what was found, where, what to do; folded — meaning, causes, impact, evidence table, verification. Healthy checks folded per area ("Maintenance: 7 checks passed"). Collected data and method at the end. |
| 9 | Suggested review order | Technical severity is not the customer's operational priority, which Keystone does not know (a test system may not need archiving). The report therefore calls the order a **suggested review order**, never a priority. It is deterministic and explainable: severity first, then the impact category of the rule in a fixed order kept in the Dictionary (data safety, availability, security, capacity, performance), then rule order. The system card (13) may later bring the environment into it. |
| 10 | Cost of the fix | Structured, per rule: `NONE` (an SQL statement or GRANT), `RELOAD`, `RESTART`, `MAINTENANCE` (locks or downtime), `PROJECT` (planning, e.g. setting up archiving). Added now and filled for new and changed rules; older rules get it later and show "—" until then. The detailed "Bedeli:" sentence stays in the recommendation. |
| 11 | Verification | A rule may carry a verification text (the query or command that shows the fix worked), shown folded in section 3; filled gradually like the cost. |
| 12 | Trend | Against the previous completed check of the same target: each finding new, ongoing or resolved. This is repository data, not a guess. Comes after the new structure. |
| 13 | System card (later) | Environment (prod / test / development), criticality, owner and maintenance window are facts Keystone cannot read. They belong to the target like the server profile (ADR-0017): entered when the target is defined, or for offline evidence as `import_bundle` parameters (as `--environment` today) or updated after import and the report rendered again; every health check keeps a copy, so an old report can be rendered as it was. Entered by the consultant, not by the customer's collection script. Not part of the first step. |

## Consequences

- The report renderer is reorganised around one list of findings; sections 1 and 2 are views of it. Texts in the Dictionary do not change for this; their repetition goes.
- Dictionary additions by migration: the priority order of impact categories, the cost of the fix per rule, the verification text type, the "decision" mark on a recommendation.
- Implementation in small pull requests, each lab-checked on a real report: (1) structure and write-once with the existing data; (2) cost of the fix and priority, action table; (3) missing-evidence panel and timeline; (4) verification texts; (5) trend. The system card follows separately.
- The pilot feedback ("what happened, what to do, impact") is answered by sections 1 and 2; it is checked again with the pilot user after (1)–(3).
