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

---

## 6. Credential tool

Encrypts a target password with `KEYSTONE_MASTER_KEY` for `target_connection.credential_data`. The password is typed hidden.

```powershell
python -m repository.tools.encrypt_credential
```

---

## 7. Tests

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

## 8. Configuration with SQL

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

---

## 9. Checking what happened

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

Log files: `logs/agent.log`, `logs/worker.log`, `logs/assessment_engine.log` (or under `KEYSTONE_LOG_DIR`).
