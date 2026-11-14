# ADR-0020 — Counter Windows

**Status:** Approved (Hasan, 2026-11-13)  
**Date:** 2026-11-13

## Context

PostgreSQL's statistics counters (checkpoints, blocks read and hit, temporary files, sequential scans) are cumulative since the last reset or loss of statistics. A single value says what happened since then, possibly months, not what happens now. Collectors store the raw counters (Capability Roadmap, "derived evidence"); P2 group 2b is the first set of rules that needs differences between snapshots.

## Decision

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Window | A rule compares the newest snapshot with the **oldest one inside its window** (`window` parameter) that is at least `min_window` older, has the same `stats_reset` and no lower counter. A reset or a failover (another server's counters) breaks the series. |
| 2 | Fallback | Without such a snapshot (offline collection, first health check): the counters since `stats_reset` when that is known and at least `min_window` ago. Ratios may also use counters since an unknown start (`stats_reset` NULL: never reset); rates (per day) may not, as the period is unknown. |
| 3 | Per rule | `window` and `min_window` are rule parameters: the window follows how fast the metric changes (Hasan: six hours already tell something). Checkpoints, cache hit, temporary files: 24 h / 6 h; sequential scans (2b-2): 7 days / 24 h; lock waits have no window (a moment). |
| 4 | Short periods | A rate measured over less than a day is a trend: the finding says so and is at most WARNING (a nightly job can fall in or out of a short period). |
| 5 | What the report shows | The period of every finding: "son 1 gün", "son 3 gün · reset date", or "since the statistics started (date unknown)". |
| 6 | Not alerting | Collection frequency (collector assignment), evaluation frequency (assessment schedule) and a rule's window are separate settings. A window looks back; it does not make a rule run less often. Crisis alerting stays with monitoring (ADR-0005, ADR-0013): a disk filling up is PG-CAP-001's finding; PG-CAP-005 shows the habit behind it. |

## Consequences

- `counter_window` in the engine serves every counter rule; loaders return the history a window can reach (8 days).
- Offline evidence is judged on totals since the reset, with the period stated; Keystone collecting regularly gives windows.
- Graphs of these counters over time (checkpoint share, lock waits) are candidates for the investigation screens (Capability Roadmap), built on the same history.
