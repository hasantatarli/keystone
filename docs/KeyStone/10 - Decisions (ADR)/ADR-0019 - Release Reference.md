# ADR-0019 — Release Reference

**Status:** Approved (Hasan, 2026-11-11)  
**Date:** 2026-11-11

## Context

Version checks were deferred to P3 (Assessment Catalogue, decision 6): they need current release data, many customer installations have no internet access, and a hand-kept list goes stale. The first pilot (hc111, PostgreSQL 14.20, support ending 2026-11-12) showed the deferral was wrong: the most important lifecycle fact of that system was missing from the report. Hasan's condition: "a version finding is worthless if the version data is wrong; show it when Keystone's machine can get the data, otherwise do not."

## Decision

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Nature | The release list is **reference data**, not Dictionary: `keystone.release_reference` (product, major, latest minor, first release, end of support) and `keystone.release_reference_source` (where it came from, `as_of`). Migrations seed it; refreshing it does not need a migration. |
| 2 | Sources | **ONLINE**: postgresql.org's versioning page, then the endoflife.date API, when Keystone's own machine reaches the internet. **FILE**: a reference file (`--export` / `--import`, JSON), for installations without internet (a quarterly package). **SEED**: the migration's values. A source answer that is not a plausible release list (too few majors, a minor of another major, dates out of order) is refused, never stored. A file older than the reference in Keystone is refused. |
| 3 | When | Best-effort refresh at the start of every health check and offline import (5 s per source); a failure is silent and the existing reference is used. By hand: `python -m repository.lifecycle.release_reference --refresh`. |
| 4 | Freshness | The reference is evidence (`KEYSTONE_RELEASE_REFERENCE`) whose capture time is its `as_of`, so the engine's ordinary freshness check decides. Latest minors change every quarter: PG-LIFE-001 accepts at most 100 days, otherwise INSUFFICIENT_EVIDENCE with the age and the refresh command; nothing is called current on old data. End-of-support dates are fixed by the five-year policy: PG-LIFE-002 accepts any age. |
| 5 | Collection | Health checks do not plan it (`REFERENCE_SOURCES`); there is nothing to collect from the target. |
| 6 | Unknown major | A major the reference does not list (a new release before the reference knows it) is not judged; the node is listed as not assessed. |

## Consequences

- PG-LIFE-001 and PG-LIFE-002 are in the product (V059); PG-LIFE-003 (operating system support) uses the same structure with another product.
- Installations without internet stay correct for support dates and honest about minors: after 100 days without a new reference, the minor check says it was not assessed and how to fix that.
- A quarterly reference package for customers (Hasan) is the export file of a Keystone with internet; producing it is an operational task, not code.
