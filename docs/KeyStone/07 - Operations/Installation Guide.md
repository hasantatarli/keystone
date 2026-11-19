# Installation Guide

Installing Keystone for a new customer, from an empty PostgreSQL server to the first health check report. Draft from the first clean install as a customer would do it (2026-11-19, Windows, PostgreSQL 17.9, database `keystone`, hc1–hc2). Commands for daily use are in [[Command Reference]]; this page is the order of the first time.

Steps marked **(manual for now)** are replaced by the target CLI (in progress); until then they are written out here.

---

## 0. What you need

| Item | Notes |
|---|---|
| A PostgreSQL server for the repository | Any supported version. Keystone needs one database it owns, no superuser. On Linux create the database with `en_US.UTF-8` or `C.UTF-8`; on Windows the default collation (for example `English_United States.1252`) works. |
| Python 3 and the requirements | `python -m pip install -r requirements.txt` in the Keystone folder. |
| A master key | One per installation; see step 3. |
| A monitoring role on every server to check | See step 5. |

Keep the repository database away from the servers it checks where possible. If it lives on a checked server, Keystone checks its own database too (its sequences appear in PG-CAP-005 missing evidence, for example).

---

## 1. Repository role and database (DBA, once)

The only step that needs a superuser. As `postgres` on the repository server:

```sql
CREATE ROLE keystone LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
\password keystone
CREATE DATABASE keystone OWNER keystone;
```

`\password` asks for the password without echo and keeps it out of the history. The role owns the database; that is enough for the installer (it creates the `keystone` and `postgresql` schemas, tables and functions; no extensions). One role: the installer, the agent, health checks and reports all connect as `keystone`.

Check that the role can log in before going on (separates `pg_hba` / password problems from installer problems):

```powershell
psql -h localhost -U keystone -d keystone -c "select current_user, current_database()"
```

---

## 2. Session settings

Every command reads the repository connection from `KEYSTONE_REPOSITORY_*` (Command Reference §1). The user has no default.

Three secrets, not to be confused:

| Secret | What it is | Where it goes |
|---|---|---|
| Repository password | Password of the `keystone` role (step 1) | `KEYSTONE_REPOSITORY_PASSWORD` |
| Master key | Not a password: an encryption key generated once (step 3); locks the target passwords stored in the repository | `KEYSTONE_MASTER_KEY` |
| Target password | Password of the monitoring role on a checked server (step 5) | Nowhere in the environment: encrypted once into `target_connection.credential_data` |

A small script outside the Keystone folder sets all of them for the current window without echo or history (for example `C:\Keystone\keystone-session.ps1`):

```powershell
param([string]$Db = "keystone", [string]$User = "keystone")
$env:KEYSTONE_REPOSITORY_DB = $Db
$env:KEYSTONE_REPOSITORY_USER = $User
$s = Read-Host "Repository password ($User)" -AsSecureString
$env:KEYSTONE_REPOSITORY_PASSWORD = [System.Net.NetworkCredential]::new("", $s).Password
$s = Read-Host "Master key" -AsSecureString
$env:KEYSTONE_MASTER_KEY = [System.Net.NetworkCredential]::new("", $s).Password
Remove-Variable s
"Keystone session ready: $User@$Db"
```

```powershell
. C:\Keystone\keystone-session.ps1        # the leading dot keeps the variables in this window
```

Do not write `$env:KEYSTONE_MASTER_KEY = '<key>'` with the real key: the line can end up in the PowerShell history file (`(Get-PSReadLineOption).HistorySavePath`).

---

## 3. Master key (once per installation)

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store it in a password manager at once. Without it the stored target passwords cannot be decrypted; a new key means encrypting every target password again. Every window that runs a health check, the agent or the credential tool needs it (step 2).

---

## 4. Install the repository

```powershell
python -m repository.install.install
```

Applies every migration in order and registers the collectors; ends with `Installer completed successfully.` Safe to run again (only pending migrations run). First install, 2026-11-19: 68 core and 29 PostgreSQL migrations, 26 collectors, as the database owner.

---

## 5. Monitoring role on each checked server (DBA)

Keystone reads, never writes. On each server to check, as a superuser:

```sql
CREATE ROLE keystone_monitor LOGIN;
\password keystone_monitor
GRANT pg_monitor TO keystone_monitor;
```

In the database Keystone connects to (usually `postgres`), so that client authentication (PG-SEC-005) can be read:

```sql
GRANT SELECT ON pg_catalog.pg_hba_file_rules TO keystone_monitor;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_hba_file_rules() TO keystone_monitor;
```

The GRANTs are per database: run them in the database named in the connection, not in another one. Sequence values (PG-CAP-005) need SELECT on the sequences; the report names them when missing. `pg_hba.conf` must allow the role from the Keystone machine.

---

## 6. Define the target (manual for now)

Encrypt the monitoring role's password (asked without echo; the output changes on every run, every output is valid):

```powershell
python -m repository.tools.encrypt_credential
```

Then in `psql -h localhost -U keystone -d keystone`, a SYSTEM with one NODE and a connection on each (a SYSTEM's own collectors need a connection on the SYSTEM too):

```sql
\prompt 'Encrypted credential: ' cred
WITH s AS (
  INSERT INTO keystone.target (name, provider, target_type, environment)
  VALUES ('<system name>', 'PostgreSQL', 'SYSTEM', '<PROD|TEST|LAB>') RETURNING target_id),
n AS (
  INSERT INTO keystone.target (parent_target_id, name, provider, target_type, environment)
  SELECT target_id, '<node name>', 'PostgreSQL', 'NODE', '<PROD|TEST|LAB>' FROM s RETURNING target_id, parent_target_id)
INSERT INTO keystone.target_connection
  (target_id, connection_name, host, port, database_name, username, auth_type, credential_data, connection_purpose)
SELECT x.target_id, x.connection_name, '<host>', 5432, 'postgres', 'keystone_monitor', 'PASSWORD', :'cred', 'DIRECT'
FROM n, LATERAL (VALUES (n.parent_target_id, '<system>-direct'), (n.target_id, '<node>-direct')) AS x(target_id, connection_name);
```

At `\prompt` paste the **encrypted** value (starts with `gAAAAA`), not the password. Check without showing it:

```sql
select connection_id, length(credential_data) as len, left(credential_data, 6) as head from keystone.target_connection;
```

`head` is `gAAAAA`; `len` is 100 for a password under 16 characters, longer for longer ones. A wrong value shows in the health check as "Credential decryption failed" on every collector.

---

## 7. First health check

```powershell
python -m repository.healthcheck.health_check --target <system id> --report tr
```

Collects, assesses and writes the HTML report; prints the health check number and the report file. A target with no active connection is refused before anything is written. If collectors fail, read the reasons:

```powershell
psql -h localhost -U keystone -d keystone -c "select target_id, collector_key, status, left(status_message, 200) from keystone.health_check_collection where health_check_id = (select max(health_check_id) from keystone.health_check) order by 1, 2"
```

Host data (disk, memory, CPU) needs a HOST (SSH) connection on Linux; Windows host data comes from the offline script only. Without it those checks are reported as not assessed, with the reason.

---

## Gaps found in the first clean install (2026-11-19)

| # | Gap | Where it goes |
|---|---|---|
| 1 | Turkish characters broken in the Windows console (`chcp 65001` before psql) | this guide |
| 2 | Windows default collation; Linux recommendation | this guide |
| 3 | The installer prints six lines per migration on a first install; the start scrolls out of the console | small fixes |
| 4 | No way to add a target except SQL | target CLI |
| 5 | Master key: what it is, how to keep it, how to give it per session — nowhere | this guide; web interface later |
| 6 | Copy and paste of the encrypted value: the plain password went in by mistake (hc1, every collector "Credential decryption failed", the password stored in clear until replaced). The message blames the master key and never says the stored value is not an encrypted one | target CLI (asks, encrypts, writes); error message |
| 7 | Preparing the monitoring role on checked servers is not part of the flow | this guide (step 5) |
| 8 | Setting the session variables is tedious and error-prone | this guide (script); web interface later |
