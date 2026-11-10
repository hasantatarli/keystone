"""Generate the offline evidence scripts from the collector files (never maintained by hand).

Two read-only SQL scripts, each one statement returning one JSON document in one cell:
  keystone_node.sql      once per server, in database postgres: SYSTEM and NODE collectors
  keystone_database.sql  once per database on every server: DATABASE and NODE_DATABASE collectors
They create nothing and run in pgAdmin, DBeaver or psql. The host scripts (Linux shell,
Windows PowerShell) are optional and copied next to them.

Usage:
    python -m repository.offline.bundle --out <folder>
"""

import argparse
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from repository.install import install as installer

BUNDLE_FORMAT = 1

# Which script runs a collector; SSH collectors are the separate host scripts.
SCRIPT_SCOPES = {"node": ("SYSTEM", "NODE"), "database": ("DATABASE", "NODE_DATABASE")}

# Data minimisation: never leaves the customer (MVP Plan, offline evidence).
REDACTED_COLUMNS = {"PG_ACTIVITY_SNAPSHOT": ("query_text",)}

# Collected from the primary only, as live: on a replica they are skipped (rows null), and some
# (WAL control functions) would fail there. CASE never evaluates the skipped subquery.
PRIMARY_ONLY_SCOPES = ("SYSTEM", "DATABASE")

HOST_SCRIPTS = ("host_snapshot.sh", "host_snapshot_windows.ps1")
COLLECT_SCRIPTS = ("keystone_collect.ps1", "keystone_collect.sh")
OFFLINE_DIR = Path(__file__).resolve().parent


def collector_body(path):
    """The collector's single statement without its trailing semicolon (comments kept)."""
    text = path.read_text(encoding="utf-8").rstrip()
    if text.endswith(";"):
        text = text[:-1]
    if ";" in re.sub(r"'(?:[^']|'')*'", "", re.sub(r"--[^\n]*|/\*.*?\*/", "", text, flags=re.S)):
        raise RuntimeError(f"{path.name}: an offline bundle needs a single statement per collector.")
    return text


def collectors_for(kind):
    """SQL collectors of one script, by key."""
    scopes = SCRIPT_SCOPES[kind]
    return sorted((c for c in installer.discover_collectors()
                   if c["execution_type"] == "SQL" and c["execution_scope"] in scopes),
                  key=lambda c: c["collector_key"])


def script_sql(kind, generated_at):
    """One SELECT returning the evidence document of this script as text."""
    parts = []
    for c in collectors_for(kind):
        row = "to_jsonb(c)"
        for column in REDACTED_COLUMNS.get(c["collector_key"], ()):
            row += f" || jsonb_build_object('{column}', NULL)"
        rows = (f"(SELECT COALESCE(jsonb_agg({row}), '[]'::jsonb) FROM (\n"
                f"{collector_body(c['path'])}\n"
                f"        ) AS c)")
        if c["execution_scope"] in PRIMARY_ONLY_SCOPES:
            rows = f"CASE WHEN pg_is_in_recovery() THEN NULL ELSE {rows} END"
        parts.append(
            f"'{c['collector_key']}', jsonb_build_object(\n"
            f"        'checksum', '{c['checksum']}',\n"
            f"        'rows', {rows})")
    run_on = ("once on every server, in database postgres" if kind == "node"
              else "once in every database (postgres included) on every server")
    return f"""/*
Keystone offline evidence: {kind} script (format {BUNDLE_FORMAT}, generated {generated_at})

Run {run_on}.
Read-only: one SELECT on system catalogs and statistics views; it creates and changes nothing.
The result is one JSON document in one cell: copy it, or save the result to a file.
Not collected: query texts, passwords, table rows.
*/

SELECT jsonb_build_object(
    'keystone_bundle', {BUNDLE_FORMAT},
    'kind', '{kind}',
    'generated_at', '{generated_at}',
    'server', jsonb_build_object(
        'system_identifier', (SELECT system_identifier::text FROM pg_control_system()),
        'address', host(inet_server_addr()),
        'port', inet_server_port(),
        'version', current_setting('server_version'),
        'in_recovery', pg_is_in_recovery(),
        'database', current_database(),
        'cluster_name', current_setting('cluster_name'),
        'collector_user', current_user,
        'captured_at', clock_timestamp()),
    'collectors', jsonb_build_object(
    {(","+chr(10)+"    ").join(parts)})
)::text AS keystone_evidence;
"""


def write_bundle(out_dir):
    """Write the scripts and guides into out_dir; returns the written paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = []
    for kind in SCRIPT_SCOPES:
        path = out / f"keystone_{kind}.sql"
        path.write_text(script_sql(kind, generated_at), encoding="utf-8")
        written.append(path)
    for name in HOST_SCRIPTS:
        source = (installer.POSTGRESQL_COLLECTORS_DIR / name if name.endswith(".sh")
                  else OFFLINE_DIR / name)
        shutil.copyfile(source, out / name)
        written.append(out / name)
    for name in COLLECT_SCRIPTS:
        shutil.copyfile(OFFLINE_DIR / name, out / name)
        written.append(out / name)
    for guide in sorted(OFFLINE_DIR.glob("KILAVUZ_*.md")):
        shutil.copyfile(guide, out / guide.name)
        written.append(out / guide.name)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the Keystone offline evidence scripts.")
    parser.add_argument("--out", required=True, help="folder to write the scripts into")
    args = parser.parse_args(argv)
    for path in write_bundle(args.out):
        print(path)


if __name__ == "__main__":
    main()
