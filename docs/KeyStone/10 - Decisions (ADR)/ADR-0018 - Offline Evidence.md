# ADR-0018 — Offline Evidence

**Status:** Approved (Hasan, 2026-11-09: Claude's choices)  
**Date:** 2026-11-09

## Context

Both first pilots cannot give Keystone a connection: Hasan's customer allows only a jump server with pgAdmin (psql and clipboard uncertain, 5–8 systems, standalone and Patroni, 2–3 databases each plus data in `postgres`); a DBA friend reaches Windows database servers only over remote desktop. MVP Plan Phase 1 already foresaw offline evidence; the external review (2026-11-09) asked for provenance: when, from which system, with which collector definition.

## Decision

| # | Topic | Decision |
| --- | --- | --- |
| 1 | Source of the SQL | Generated from the collector files (`repository.offline.bundle`); never a hand-kept copy. |
| 2 | Runs | Per server: `keystone_node.sql` once in `postgres` (SYSTEM and NODE collectors), `keystone_database.sql` once per database (DATABASE and NODE_DATABASE). |
| 3 | Output | One `SELECT`, one JSON document in one cell. Copy, pgAdmin "save results to file" (CSV) or `psql -At`; the importer reads all three. |
| 4 | Host | Optional: the Linux host collector script or a Windows PowerShell script printing the same sections, so one parser reads both. Without it, hardware-dependent checks are not assessed. |
| 5 | Provenance | Every file: `system_identifier`, address and port, version, recovery state, database, `cluster_name`, user, capture time, and the checksum of every collector. Stored with the check (`health_check.bundle_info`, `source = OFFLINE`, `imported_at`). |
| 6 | Import | `repository.offline.import_bundle`: files to nodes by connection address, file name or `--node`; refused for mixed or unknown systems and duplicates; a collector whose checksum changed is not imported. Rows go through the live handlers; one capture time per collection when several files feed it. |
| 7 | Time | Judged as of the latest capture time (`evaluation_time`); the check's start and end are the capture times. A spread above 10 minutes is warned. |
| 8 | Minimisation | Query texts are nulled in the script itself (`PG_ACTIVITY_SNAPSHOT.query_text`); no table data or passwords exist in any collector. Masking names is not in the first version (backlog). |
| 9 | Windows | Data directories with drive letters are matched to their volume (`C:\` ↔ `C:/...`); `effective_io_concurrency` is not recommended there (ADR-0017). |

## Consequences

- Engine, rules and report are unchanged: offline evidence is the same rows, from another route.
- The scripts must stay single statements; the generator refuses a collector with several.
- Customers can read exactly what is collected: the SQL files are the collectors.
- Not yet: masking of names, an export-side checksum of the whole file, a Windows host collector over the network (WinRM).
