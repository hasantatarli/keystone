# ADR-0015 — Scheduling of Collection and Assessment

**Status:** Approved  
**Date:** 2026-10-14

## Context

Keystone's core scenario is unattended, continuous assessment in long-term DBA engagements (Product Strategy → Usage Scenarios). Different evidence changes at different speeds: session activity may be collected every minute, transaction ID age once a day. Assessments evaluate whatever evidence is available and notify the engineer when conclusions change (ADR-0013).

Today collection and assessment are started by hand. `collector_assignment` already has `execution_mode` (`ON_DEMAND` / `SCHEDULED`) and `interval_seconds`, but nothing turns them into work, and there is no place to schedule assessments.

## Decision

### Collection and assessment are scheduled independently

- **Collector scheduling:** each collector assignment runs at its own interval and produces queued work.
- **Assessment scheduling:** each assessment runs for a target at its own interval and evaluates the latest evidence, subject to each rule's freshness (`max_age_seconds`).

Collection frequency and evidence freshness stay separate concepts (Design History, 2026-09). An assessment does not trigger collection in continuous mode.

### One collection path

All collection goes through the collection queue and the worker, whether started by the scheduler or by a person. A manual assessment (prospective customer, one-off health check) is the same pipeline triggered once: queue the required collectors now, let the worker drain them, then run the assessments. There is no second collection mechanism.

### Schedules are per target and editable

- Collector intervals stay in `keystone.collector_assignment` (per target).
- Assessment intervals go into a new table `keystone.assessment_schedule`: assessment, target, interval, enabled.
- Every collector and assessment has a **default interval**: collectors declare it in their file header metadata, assessments in the Dictionary. When a target is set up, defaults are copied into its rows; the engineer, and later the web interface, change them per environment (load, size, criticality).

### Intervals are stored in seconds

All intervals are stored as seconds in the database, like `max_age_seconds`. Unit selection (seconds, minutes, hours, days) is a user-interface concern: the interface converts on save and shows the largest unit that divides the value exactly. No unit column is stored, so every comparison and calculation uses one unit.

### Consistency warning

When a collector interval is longer than the freshness limit of a rule that depends on that collector's evidence, the rule will usually end INSUFFICIENT_EVIDENCE. Saving such a configuration produces a warning; it is not blocked. The same check also reports a required collector that is not scheduled for the target at all. It is defined once, as the view `keystone.schedule_consistency_warning`; the agent logs its rows when it starts scheduling, and the web interface will show the same rows. It describes configuration, not database health.

### Execution: Keystone Agent

Schedules are executed by the Keystone Agent, a long-running service like SQL Server Agent, independent of any user interface (not a web-hosted job runner, which stops when its host recycles).

- **Generic scheduler, job adapters.** The scheduler only decides *when*; each job type (collector assignments now, assessment schedules next) is an adapter that lists its items with their last run and knows how to start one.
- **Fixed grid.** Items run on a clock-aligned grid: a 60 s item at every full minute, a 3600 s item at every full hour. Start times do not drift with run duration.
- **Missed slots are skipped.** A slot that begins while the previous run is still going (or still queued) is not run; the item waits for the next slot. A failed run counts as a run.
- **No catch-up after downtime.** When the agent comes back, an overdue item runs once immediately, then returns to the grid.
- **Parallel execution with two limits.** A continuous worker pool runs tasks in parallel (agent parameter, default 20); a freed slot takes the next task at once. Each target has `max_concurrent_tasks` (default 3), because every task opens a connection to the monitored database: tasks of one target queue up, tasks of different targets run in parallel.
- **Scale out, not up.** More agents can run side by side on other machines: only one schedules (advisory lock), all take work from the shared queue. Schedule lag (`started_at - scheduled_at`) is recorded and logged when it grows; that is the signal to add an agent.
- **Offset.** A schedule may run a fixed number of seconds after each slot. Assessments default to 30 s, so evidence collected at the start of the slot is already stored when they evaluate. The same mechanism can later spread collectors that share an interval.
- **Assessments run inside the agent.** They read only the repository and take seconds, so they run in a small pool of their own (2 threads) instead of a queue. Runs left RUNNING by a stopped agent are marked FAILED when the next scheduler starts.
- **Later: worker pools.** When other database types or customer-network agents arrive, an agent will declare which work it can take (provider, network) and claim only that. Not built now; nothing in the current design prevents it.

### Out of scope for now

- Time windows (for example, run only at night) and event-triggered assessments. Simple intervals are sufficient for the MVP; both can be added as columns later.
- Per-target threshold overrides. These remain deferred; this decision is about timing only.

## Consequences

- One scheduler loop can serve both collector assignments and assessment schedules.
- Capacity grows by adding agents; the per-target limit keeps load on customer databases bounded regardless of how many agents run.
- Manual and continuous assessment share code, history and failure handling.
- Different environments can be tuned without code changes; the web interface edits rows only.
- Defaults must be maintained with each new collector (header metadata) and assessment (migration).

## Related hardening (not part of this decision)

`PG_TABLE_CAPACITY` calls relation size functions that take AccessShareLock on every relation for the duration of the collector transaction. A DDL arriving meanwhile waits, and later queries queue behind it. Collector sessions should get a short `lock_timeout` and heavy collectors a shorter `statement_timeout`. Tracked in DEVELOPMENT_STATUS.
