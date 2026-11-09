# Command Reference

How to run Keystone components, with their variations. All commands run from the repository root (`C:\Yazılım\keystone` in the lab). Background and rules are in the ADRs; this page is only the "how".

Shell syntax differs: examples are given for **PowerShell** (Windows lab) and **bash** (Linux) where they differ.

---

## 1. Environment

Every component reads the repository connection and secrets from environment variables.

| Variable | Purpose | Default |
|---|---|---|
| `KEYSTONE_REPOSITORY_HOST` | Repository PostgreSQL host | `localhost` |
| `KEYSTONE_REPOSITORY_PORT` | Port | `5432` |
| `KEYSTONE_REPOSITORY_DB` | Database | `keystone_lab` |
| `KEYSTONE_REPOSITORY_USER` | User | `postgres` |
| `KEYSTONE_REPOSITORY_PASSWORD` | Password | none |
| `KEYSTONE_MASTER_KEY` | Decrypts target credentials (worker, agent, credential tool) | none |
| `KEYSTONE_LOG_DIR` | Log file directory (`<component>.log`, rotating) | `logs` |
| `KEYSTONE_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`… | `INFO` |

Set for the current session:

```powershell
# PowerShell
$env:KEYSTONE_LOG_LEVEL = "DEBUG"
# clear again
Remove-Item Env:KEYSTONE_LOG_LEVEL
```

```bash
# bash
export KEYSTONE_LOG_LEVEL=DEBUG
unset KEYSTONE_LOG_LEVEL
```

> In PowerShell `set NAME=value` does **not** set an environment variable (it creates a PowerShell variable). Use `$env:NAME = "value"`.

Never print the master key or passwords to the console or into documents.

---

## 2. Install and update

Dependencies (once per machine, and after `requirements.txt` changes):

```powershell
python -m pip install -r requirements.txt
```

Get the latest code:

```powershell
git checkout main
git pull
```

Test a pull request branch before merge:

```powershell
git fetch
git checkout <branch-name>      # first time
git pull                        # branch already checked out, new commits pushed
```

Install or upgrade the repository (applies new migrations; safe to run again):

```powershell
python -m repository.install.install
```

---

## 3. Keystone Agent (continuous operation)

Long-running service: schedules collectors and assessments and runs them (ADR-0015).

```powershell
python -m repository.agent.agent
python -m repository.agent.agent --max-workers 10        # fewer parallel collection tasks (default 20)
python -m repository.agent.agent --poll-seconds 5        # check the queue more often (default 10)
python -m repository.agent.agent --help
```

- Stop: `Ctrl+C` (or SIGTERM under systemd). Running tasks finish first.
- Detailed output (collected rows, rule-by-rule assessment detail): set `KEYSTONE_LOG_LEVEL=DEBUG` before starting.
- Several agents may run at once (other machines too): one schedules, all execute.

Linux service: `deploy/systemd/keystone-agent.service` (instructions in the file header).

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now keystone-agent
sudo systemctl status keystone-agent
journalctl -u keystone-agent -f
```

Windows service: not yet available (backlog).

---

## 4. Worker (one pass, for tests)

Drains the collection queue once and exits. Not needed while the agent runs.

```powershell
python -m repository.worker.worker
```

Queue one collector by hand, then run the worker:

```sql
INSERT INTO keystone.collection_queue (assignment_id, status, scheduled_at)
VALUES (<assignment_id>, 'WAITING', now());
```

---

## 5. Assessment engine (manual run)

Runs one assessment for one target with rule-by-rule output.

```powershell
python -m repository.intelligence.assessment_engine --assessment PG_TRANSACTION_HEALTH --target 1
python -m repository.intelligence.assessment_engine --assessment PG_CONNECTION_HEALTH  --target 1
python -m repository.intelligence.assessment_engine --assessment PG_REPLICATION_HEALTH --target 1
python -m repository.intelligence.assessment_engine        # default: PG_CONNECTION_HEALTH, target 1
python -m repository.intelligence.assessment_engine --help
```

The engine evaluates the evidence already in the repository; it does not collect.

Assessments (2026-11-02): `PG_TRANSACTION_HEALTH`, `PG_REPLICATION_HEALTH`, `PG_CONNECTION_HEALTH`, `PG_CAPACITY_HEALTH`, `PG_CONFIGURATION_HEALTH`, `PG_BACKUP_HEALTH`, `PG_SECURITY_HEALTH`, `PG_MAINTENANCE_HEALTH`, `PG_INDEX_HEALTH`, `PG_CONFIGURATION_TUNING`. Configuration check alone: `python -m repository.healthcheck.health_check --target <id> --assessment PG_CONFIGURATION_TUNING --report tr`. Current list: `SELECT assessment_key FROM keystone.assessment_definition ORDER BY 1;`

---

## 6. Health check (one-off)

Collects the evidence the assessments need (plus report context: database inventory, instance inventory and configuration on every node, host snapshot where assigned), then runs the assessments and prints a summary. A SYSTEM target includes its NODE targets. Works with or without a running agent. Since V031 the host snapshot is rule evidence (PG-CAP-001) on every node: nodes without an SSH (HOST) connection are listed as NOT_COLLECTED.

```powershell
python -m repository.healthcheck.health_check --target 1
python -m repository.healthcheck.health_check --target 1 --assessment PG_TRANSACTION_HEALTH
python -m repository.healthcheck.health_check --target 1 --wait-minutes 5     # per-collector wait limit (default 10)
python -m repository.healthcheck.health_check --target 1 --report tr          # also write the HTML report (tr | en)
python -m repository.healthcheck.health_check --help
```

- Missing collector assignments are created as ON_DEMAND only when the target has a suitable connection; otherwise the collection is listed as NOT_COLLECTED with the reason.
- A collector past the wait limit is not waited for (WAIT_LIMIT); the command still waits for it to end before exiting.

### Report of an existing health check

Writes the HTML report from data already in the repository; it does **not** collect. Run a new health check for current data.

```powershell
python -m repository.report.health_check_report --target 1                      # latest completed check of target 1
python -m repository.report.health_check_report --health-check 7 --lang en
python -m repository.report.health_check_report --target 1 --output C:\temp\report.html
```

- Default file: `reports/<target>_<yyyymmdd-hhmm>_hc<id>_<lang>.html` (check start time); a new check never overwrites an older report. The command prints which check it reports.
- Two tabs: Executive Summary and Technical Details; printing shows both.
- Context data (servers, disks, databases) comes only from that check's time window; data a check could not collect is shown as not collected, never from an older check.

```sql
-- health checks of a target
SELECT * FROM keystone.health_check WHERE target_id = 1 ORDER BY health_check_id DESC;

-- what a health check collected
SELECT c.collector_key, t.name, c.purpose, c.status, c.status_message, rh.rows_collected
FROM keystone.health_check_collection c
JOIN keystone.target t ON t.target_id = c.target_id
LEFT JOIN keystone.collector_run_history rh ON rh.task_id = c.task_id
WHERE c.health_check_id = <id>
ORDER BY c.purpose DESC, c.collector_key, t.name;

-- its rule outcomes
SELECT ad.assessment_key, rd.rule_key, res.outcome, res.max_severity, res.reason
FROM keystone.assessment_run ar
JOIN keystone.assessment_definition ad ON ad.assessment_id = ar.assessment_id
JOIN keystone.assessment_result res ON res.assessment_run_id = ar.assessment_run_id
JOIN keystone.rule_definition rd ON rd.rule_id = res.rule_id
WHERE ar.health_check_id = <id>
ORDER BY ad.assessment_key, rd.rule_key;
```

---

### Offline health check (no Keystone connection, ADR-0018)

For customers where Keystone cannot connect (jump server, GUI client only). The customer side runs read-only scripts; the files are imported here and judged as of their capture time.

1. Generate the scripts (from the collector files; never edited by hand) and give the folder to whoever runs them. `KILAVUZ_TOPLAMA.md` inside explains the steps in Turkish:

```powershell
python -m repository.offline.bundle --out C:\keystone-offline
```

2. Register the system without connections (once). Name the nodes as the files will be named:

```sql
INSERT INTO keystone.target (name, provider, target_type, environment) VALUES ('musteri-db', 'PostgreSQL', 'SYSTEM', 'PROD') RETURNING target_id;   -- e.g. 20
INSERT INTO keystone.target (name, provider, target_type, environment, parent_target_id) VALUES ('db-1', 'PostgreSQL', 'NODE', 'PROD', 20), ('db-2', 'PostgreSQL', 'NODE', 'PROD', 20);
-- A standalone server can be one NODE target without a SYSTEM.
```

3. Import the files and write the report:

```powershell
python -m repository.offline.import_bundle --target 20 db-1_node.json db-1_postgres.json db-1_app.json db-2_node.json --host db-1=db-1_host.txt --report tr
```

- Files are matched to nodes by a connection address if one is defined, else by the file name starting with the node name; `--node db-2=file.json` says it explicitly. One node: any name works.
- Refused before anything is written: files of different systems (`system_identifier`), a system different from what Keystone knew, the same script twice for one server and database.
- A collector changed since the scripts were generated is not imported (FAILED: generate the scripts again). Missing files make their collections NOT_COLLECTED; the rules then say "not assessed".
- The report header says "collected offline" with the import time; the date is the capture time.

## 7. Credential tool

Encrypts a target password with `KEYSTONE_MASTER_KEY` for `target_connection.credential_data`. The password is typed hidden.

```powershell
python -m repository.tools.encrypt_credential
```

Generate a master key (Fernet) once per Keystone installation and keep it in a password manager; without it the stored credentials cannot be decrypted:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Changing the key (for example after it was exposed): set the new key, encrypt every target password again with the credential tool, update `keystone.target_connection.credential_data` for every connection in one transaction, then run a health check. A connection left with the old encryption fails with "Credential decryption failed". A rotation tool is in the backlog.

---

## 8. Tests

```bash
# all tests (needs PostgreSQL binaries for disposable test servers)
python -B -m unittest discover -s tests -p "test_*.py"
# one file
python -B -m unittest discover -s tests -p test_scheduler.py -v
```

Linux sandbox variant used in development:

```bash
su pgtest -c "cd $PWD && KEYSTONE_TEST_PG_BIN=/usr/lib/postgresql/16/bin python3 -B -m unittest discover -s tests -p 'test_*.py'"
```

---

## 9. Configuration with SQL

### Collector schedules

```sql
-- current assignments of a target
SELECT ca.assignment_id, cd.collector_key, ca.execution_mode, ca.interval_seconds, ca.is_enabled
FROM keystone.collector_assignment ca
JOIN keystone.collector_definition cd USING (collector_id)
WHERE ca.target_id = 1
ORDER BY cd.collector_key;

-- schedule a collector every 60 s
UPDATE keystone.collector_assignment
SET execution_mode = 'SCHEDULED', interval_seconds = 60
WHERE assignment_id = <id>;

-- back to manual only
UPDATE keystone.collector_assignment
SET execution_mode = 'ON_DEMAND', interval_seconds = NULL
WHERE assignment_id = <id>;

-- per-target limit of parallel collection tasks (default 3)
UPDATE keystone.target SET max_concurrent_tasks = 2 WHERE target_id = 1;

-- long-running warning: fixed threshold for an assignment whose long runs are known
-- (default NULL = 3x median of the last 20 successful runs, min 120 s; 600 s until 5 runs)
UPDATE keystone.collector_assignment SET expected_max_seconds = 3600 WHERE assignment_id = <id>;
UPDATE keystone.collector_assignment SET expected_max_seconds = NULL WHERE assignment_id = <id>;
```

### Assessment schedules

```sql
-- create default schedules for a target (idempotent; returns how many were created)
SELECT keystone.apply_default_assessment_schedules(1);

-- current schedules
SELECT ad.assessment_key, s.interval_seconds, s.offset_seconds, s.is_enabled
FROM keystone.assessment_schedule s
JOIN keystone.assessment_definition ad USING (assessment_id)
WHERE s.target_id = 1;

-- change interval / disable
UPDATE keystone.assessment_schedule s
SET interval_seconds = 3600
FROM keystone.assessment_definition ad
WHERE ad.assessment_id = s.assessment_id
  AND ad.assessment_key = 'PG_REPLICATION_HEALTH'
  AND s.target_id = 1;
```

Offset must stay smaller than the interval (default 30 s).

### Configuration warnings

```sql
SELECT * FROM keystone.schedule_consistency_warning WHERE target_id = 1;
```

### Server profile (ADR-0017)

Facts Keystone cannot collect, on the target the health check runs on (the SYSTEM, or a NODE without one). NULL means not given: OLTP, dedicated and SSD are assumed, and the report says so. The management type has no default (V052): until it is given, the report writes every configuration command as a comment.

```sql
UPDATE keystone.target
SET workload_type = 'OLTP',      -- OLTP | OLAP | MIXED
    dedicated     = true,        -- the server runs only PostgreSQL
    storage_type  = 'SSD',       -- SSD | HDD
    cluster_manager = 'PATRONI'  -- PATRONI (patronictl edit-config) | NONE (ALTER SYSTEM)
WHERE target_id = 6;
```

Each health check keeps the profile it used (`health_check.target_profile`).

---

## 10. Checking what happened

```sql
-- collector runs and start lag
SELECT cd.collector_key, rh.scheduled_at, rh.started_at,
       round(extract(epoch FROM rh.started_at - rh.scheduled_at)::numeric, 2) AS lag_s,
       rh.status, rh.rows_collected, rh.error_message
FROM keystone.collector_run_history rh
JOIN keystone.collector_assignment ca USING (assignment_id)
JOIN keystone.collector_definition cd USING (collector_id)
WHERE ca.target_id = 1 AND rh.started_at > now() - interval '30 minutes'
ORDER BY rh.started_at;

-- queue right now
SELECT task_id, assignment_id, status, scheduled_at, started_at, worker_id, heartbeat_at, retry_count
FROM keystone.collection_queue
ORDER BY scheduled_at;

-- assessment runs
SELECT ad.assessment_key, ar.assessment_run_id, ar.scheduled_at, ar.started_at, ar.status, ar.status_message
FROM keystone.assessment_run ar
JOIN keystone.assessment_definition ad USING (assessment_id)
WHERE ar.started_at > now() - interval '30 minutes'
ORDER BY ar.started_at;

-- rule outcomes
SELECT ad.assessment_key, ar.started_at, rd.rule_key, res.outcome, res.max_severity, res.reason
FROM keystone.assessment_result res
JOIN keystone.assessment_run ar USING (assessment_run_id)
JOIN keystone.assessment_definition ad ON ad.assessment_id = ar.assessment_id
JOIN keystone.rule_definition rd ON rd.rule_id = res.rule_id
WHERE ar.started_at > now() - interval '30 minutes'
ORDER BY ar.started_at, rd.rule_key;

-- technical events (warnings, errors, start/stop)
SELECT logged_at, level, component, logger_name, message, context
FROM keystone.event_log
ORDER BY logged_at DESC
LIMIT 50;
```

Log files: `logs/agent.log`, `logs/worker.log`, `logs/assessment_engine.log`, `logs/health_check.log` (or under `KEYSTONE_LOG_DIR`).
