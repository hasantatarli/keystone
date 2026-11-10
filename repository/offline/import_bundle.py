"""Import offline evidence files into a health check (MVP Plan Phase 1, offline evidence).

The files come from the read-only scripts of repository.offline.bundle (one node file per
server, one database file per database and server) and, optionally, the host scripts. They
are written into the same provider tables the collectors use, through the same handlers, and
judged as of their capture time; the report says the evidence was offline.

Usage:
    python -m repository.offline.import_bundle --target 5 node.json app.json postgres.json \\
        [--host host.txt] [--node postgre-1=p1_node.json] [--report tr]
"""

import argparse
import csv
import getpass
import hashlib
import io
import json
import re
import shutil
import tarfile
import tempfile
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from psycopg.types.json import Jsonb

from repository.common.server_profile import server_profile
from repository.healthcheck import health_check as hc
from repository.install import install as installer
from repository.intelligence import assessment_engine
from repository.offline.bundle import BUNDLE_FORMAT
from repository.worker import worker

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$")
# Scripts run one after another; the short-lived evidence (sessions, 10 minutes) must stay comparable.
SPREAD_WARNING_SECONDS = 600


class BundleError(Exception):
    """A file or the set of files cannot be imported; the message says what to do."""


# ----------------------------------------------------------------------------- reading

def decode(raw):
    """File bytes as text: UTF-8 (with or without BOM) or UTF-16 (Windows PowerShell 5 '>')."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def document_text(raw):
    """The JSON text of one result, whether pasted, saved by pgAdmin (CSV) or written by psql -At."""
    text = raw.lstrip("\ufeff").strip()
    if text.startswith("{"):
        if text.startswith('{""'):                 # copied with CSV quoting: quotes doubled, no outer pair
            return text.replace('""', '"')
        return text
    for row in csv.reader(io.StringIO(text)):
        for cell in row:
            if cell.strip().startswith("{"):
                return cell.strip()
    raise BundleError("no Keystone evidence document found (expected one JSON value)")


def typed(value):
    """JSON back to the types the collectors return: timestamps as datetimes, numbers exact."""
    if isinstance(value, str) and TIMESTAMP.match(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, list):
        return [typed(v) for v in value]
    if isinstance(value, dict):
        return {k: typed(v) for k, v in value.items()}
    return value


def read_evidence(path):
    raw = Path(path).read_bytes()
    try:
        doc = json.loads(document_text(decode(raw)), parse_float=Decimal)
    except (UnicodeDecodeError, ValueError) as exc:
        raise BundleError(f"{path}: not readable as Keystone evidence ({exc})") from exc
    if doc.get("keystone_bundle") != BUNDLE_FORMAT or doc.get("kind") not in ("node", "database"):
        raise BundleError(f"{path}: not a Keystone evidence file of format {BUNDLE_FORMAT}")
    doc = typed(doc)
    doc["file"] = str(path)
    doc["sha256"] = hashlib.sha256(raw).hexdigest()
    return doc


def read_host(path):
    """Host script output (Linux or Windows) as collector rows, at the time the script ran."""
    text = decode(Path(path).read_bytes())
    rows = worker.parse_host_snapshot_output(text)
    match = re.search(r"^===CAPTURED_AT===\s*\n\s*(\S+)", text, re.MULTILINE)
    if match:
        captured = typed(match.group(1))
        for r in rows:
            r["captured_at"] = captured
    else:
        for r in rows:
            r["captured_at"] = None                     # set from the node's evidence below
    return {"file": str(path), "rows": rows, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def expand(paths, workdir):
    """Evidence and host files from the given paths; archives of the collector scripts are unpacked."""
    evidence, hosts = [], []
    for path in map(Path, paths):
        if path.suffix.lower() == ".zip" or path.name.lower().endswith((".tar.gz", ".tgz")):
            target = Path(workdir) / path.name
            if path.suffix.lower() == ".zip":
                with zipfile.ZipFile(path) as archive:
                    archive.extractall(target)
            else:
                with tarfile.open(path) as archive:
                    archive.extractall(target, filter="data")
            found = sorted(p for p in target.rglob("*") if p.is_file())
        else:
            found = [path]
        for f in found:
            if f.name.lower().endswith("_host.txt"):
                hosts.append(str(f))
            elif f.suffix.lower() in (".json", ".csv", ".txt"):
                evidence.append(str(f))
    return evidence, hosts


# ----------------------------------------------------------------------------- matching

def split_mapping(values):
    """--node NAME=FILE / --host NAME=FILE → {file: name}; a bare FILE maps to None."""
    mapping = {}
    for value in values or ():
        name, sep, file = value.partition("=")
        if sep:
            mapping[str(Path(file))] = name
        else:
            mapping[str(Path(value))] = None
    return mapping


def match_node(conn, doc_or_file, nodes, explicit, address=None, port=None):
    """The node target a file belongs to: explicit, the only node, the connection address, or the file name."""
    file = doc_or_file
    by_name = {n["name"].lower(): n for n in nodes}
    name = explicit.get(str(Path(file)))
    if name:
        if name.lower() not in by_name:
            raise BundleError(f"{file}: no node named {name} in this target")
        return by_name[name.lower()]
    if len(nodes) == 1:
        return nodes[0]
    if address:
        row = conn.execute(
            "SELECT target_id FROM keystone.target_connection WHERE target_id = ANY(%s) "
            "AND host = %s AND (port IS NULL OR port = %s) AND is_active LIMIT 1",
            ([n["target_id"] for n in nodes], address, port)).fetchone()
        if row:
            return next(n for n in nodes if n["target_id"] == row["target_id"])
    base = Path(file).name.lower()
    found = [n for n in nodes if re.match(re.escape(n["name"].lower()) + r"(?![a-z0-9])", base)]
    if len(found) == 1:
        return found[0]
    raise BundleError(f"{file}: cannot tell which server it comes from; name the file after the server "
                      f"(for example {nodes[0]['name']}_node.json) or use --node NAME=FILE")


def check_identity(conn, docs, node_of):
    """All files from one PostgreSQL system, and the same system Keystone knew before."""
    identifiers = {d["server"]["system_identifier"] for d in docs}
    if len(identifiers) > 1:
        raise BundleError("the files come from different PostgreSQL systems (system_identifier "
                          + ", ".join(sorted(identifiers)) + ")")
    identifier = identifiers.pop()
    for node in {id(n): n for n in node_of.values()}.values():
        known = conn.execute(
            "SELECT system_identifier FROM postgresql.instance_inventory WHERE target_id = %s "
            "AND system_identifier IS NOT NULL", (node["target_id"],)).fetchone()
        if known and known["system_identifier"] != identifier:
            raise BundleError(f"{node['name']} is known as system {known['system_identifier']}, the files "
                              f"are from system {identifier}: wrong target or wrong files")
    return identifier


# ----------------------------------------------------------------------------- import

def gather(scope, plan_target, docs, node_of, primary_id, hosts):
    """(rows, files) for one planned collection, or (None, reason) when the bundle has none."""
    tid = plan_target["target_id"]
    if scope == "HOST":
        host = hosts.get(tid)
        return (host["rows"], [host["file"]]) if host else (None, "host script output not given")
    if scope in ("SYSTEM", "DATABASE"):
        if primary_id is None:
            return None, "no node file of a primary"
        tid = primary_id
    kind = "node" if scope in ("SYSTEM", "NODE") else "database"
    chosen = [d for d in docs if d["kind"] == kind and node_of[d["file"]]["target_id"] == tid]
    if not chosen:
        what = "node file" if kind == "node" else "database files"
        return None, f"no {what} of this server"
    return chosen, [d["file"] for d in chosen]


def import_bundle(connect, target_id, files, hosts=None, node_map=None, host_map=None,
                  assessment_key=None, requested_by=None):
    """Returns (health_check_id, warnings). Raises BundleError before writing anything if files are wrong."""
    docs = [read_evidence(f) for f in files]
    host_files = list(hosts or ())
    current = {c["collector_key"]: c for c in installer.discover_collectors()}
    warnings = []

    with connect() as conn:
        target, nodes = hc.load_target_tree(conn, target_id)
        node_targets = nodes or ([target] if target["target_type"] == "NODE" else [])
        if not node_targets:
            raise BundleError(f"target {target_id} has no node to import into")
        explicit = split_mapping(node_map)
        node_of = {d["file"]: match_node(conn, d["file"], node_targets, explicit,
                                         d["server"].get("address"), d["server"].get("port"))
                   for d in docs}
        identifier = check_identity(conn, docs, node_of)

        seen = {}
        for d in docs:
            key = (node_of[d["file"]]["target_id"], d["kind"], d["server"]["database"] if d["kind"] == "database" else "")
            if key in seen:
                raise BundleError(f"{d['file']} and {seen[key]} are the same script on the same server "
                                  f"and database; keep one")
            seen[key] = d["file"]
        primaries = {node_of[d["file"]]["target_id"] for d in docs
                     if d["kind"] == "node" and not d["server"]["in_recovery"]}
        if len(primaries) > 1:
            raise BundleError("more than one node file says it is the primary")
        primary_id = primaries.pop() if primaries else None
        if primary_id is None:
            warnings.append("no node file of a primary: system-wide evidence is missing")

        hosts_by_node = {}
        explicit_hosts = split_mapping(host_map)
        for f in host_files:
            node = match_node(conn, f, node_targets, explicit_hosts)
            hosts_by_node[node["target_id"]] = read_host(f)

        times = [d["server"]["captured_at"] for d in docs]
        first, last = min(times), max(times)
        if (last - first).total_seconds() > SPREAD_WARNING_SECONDS:
            warnings.append(f"the scripts ran {int((last - first).total_seconds() // 60)} minutes apart; "
                            "short-lived evidence (sessions, replication) may be judged stale")
        for node_id, host in hosts_by_node.items():
            node_doc = next((d for d in docs if d["kind"] == "node"
                             and node_of[d["file"]]["target_id"] == node_id), None)
            for r in host["rows"]:
                if r["captured_at"] is None:
                    r["captured_at"] = node_doc["server"]["captured_at"] if node_doc else last

        assessment_keys = hc.load_assessments(conn, target["provider"], assessment_key)
        info = {"system_identifier": identifier, "warnings": warnings, "files": [
            {"file": Path(d["file"]).name, "sha256": d["sha256"], "kind": d["kind"],
             "node": node_of[d["file"]]["name"], "database": d["server"]["database"],
             "address": d["server"].get("address"), "in_recovery": d["server"]["in_recovery"],
             "captured_at": d["server"]["captured_at"].isoformat()} for d in docs]
            + [{"file": Path(h["file"]).name, "sha256": h["sha256"], "kind": "host",
                "node": next(n["name"] for n in node_targets if n["target_id"] == tid)}
               for tid, h in hosts_by_node.items()]}
        health_check_id = conn.execute(
            "INSERT INTO keystone.health_check (target_id, status, requested_by, target_profile, source, "
            "started_at, imported_at, bundle_info) VALUES (%s, 'RUNNING', %s, %s, 'OFFLINE', %s, "
            "clock_timestamp(), %s) RETURNING health_check_id",
            (target_id, requested_by, Jsonb(server_profile(target)), first, Jsonb(info)),
        ).fetchone()["health_check_id"]
        conn.commit()

        plan, definitions = hc.plan_collections(conn, target, nodes, assessment_keys)
        for plan_target, key, purpose, optional in plan:
            definition = definitions.get(key)
            if definition is None:
                hc.record_collection(conn, health_check_id, plan_target["target_id"], key, purpose,
                                     None, None, "NOT_COLLECTED", "collector is not defined or not active")
                continue
            scope = "HOST" if definition["execution_type"] == "SSH" else definition["execution_scope"]
            found, files_used = gather(scope, plan_target, docs, node_of, primary_id, hosts_by_node)
            if found is None:
                if not optional:
                    hc.record_collection(conn, health_check_id, plan_target["target_id"], key, purpose,
                                         None, None, "NOT_COLLECTED", f"offline: {files_used}")
                continue
            try:
                rows = found if scope == "HOST" else collector_rows(found, key, current)
                with conn.transaction():
                    if rows:
                        worker.persist_collector_result(conn, {
                            "target_id": plan_target["target_id"], "collector_key": key,
                            "collector_name": key, "task_id": None, "assignment_id": None}, rows)
                    hc.record_collection(conn, health_check_id, plan_target["target_id"], key, purpose,
                                         None, None, "SUCCESS",
                                         "offline: " + ", ".join(Path(f).name for f in files_used))
            except Exception as exc:
                hc.record_collection(conn, health_check_id, plan_target["target_id"], key, purpose,
                                     None, None, "FAILED", f"offline: {exc}")
        conn.commit()
        uncollected = hc.uncollected_evidence(conn, health_check_id)

    # Judged as of the capture: importing a day later does not make the evidence stale.
    for key in assessment_keys:
        with connect() as conn:
            assessment_engine.run_assessment(conn, key, target_id, evaluation_time=last,
                                             health_check_id=health_check_id, uncollected=uncollected)
    with connect() as conn:
        conn.execute("UPDATE keystone.health_check SET status = 'COMPLETED', finished_at = %s "
                     "WHERE health_check_id = %s", (last, health_check_id))
        conn.commit()
    return health_check_id, warnings


def collector_rows(chosen, key, current):
    """Rows of one collector from the chosen files; one capture time when several files feed it."""
    rows = []
    for d in chosen:
        entry = d["collectors"].get(key)
        if entry is None:
            raise BundleError(f"{Path(d['file']).name} has no {key}; generate the scripts again")
        if current.get(key) and entry["checksum"] != current[key]["checksum"]:
            raise BundleError(f"{key} changed since {Path(d['file']).name} was generated; "
                              "generate the scripts again and collect anew")
        rows.extend(entry["rows"])
    if len(chosen) > 1:
        # Handlers expect one capture per collection, as the live fan-out over databases gives.
        captured = max(d["server"]["captured_at"] for d in chosen)
        for r in rows:
            r["captured_at"] = captured
    return rows


# ----------------------------------------------------------------------------- command line

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Import Keystone offline evidence into a health check.")
    parser.add_argument("--target", type=int, required=True, help="target_id (SYSTEM includes its nodes)")
    parser.add_argument("files", nargs="+",
                        help="the collector's archive (.zip / .tar.gz) or evidence files")
    parser.add_argument("--host", action="append", default=[], metavar="[NODE=]FILE",
                        help="host script output (Linux or Windows); NODE= when the system has several")
    parser.add_argument("--node", action="append", default=[], metavar="NODE=FILE",
                        help="the server a file comes from, when Keystone cannot tell")
    parser.add_argument("--assessment", help="only this assessment_key (default: all enabled)")
    parser.add_argument("--report", choices=["tr", "en"], help="also write the HTML report")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        user = getpass.getuser()
    except Exception:
        user = None
    workdir = tempfile.mkdtemp(prefix="keystone_import_")
    try:
        files, found_hosts = expand(args.files, workdir)
        hosts = [h.partition("=")[2] if "=" in h else h for h in args.host] + found_hosts
        health_check_id, warnings = import_bundle(
            worker.connect_repository, args.target, files, hosts, args.node,
            [h for h in args.host if "=" in h], args.assessment, user)
    except BundleError as exc:
        raise SystemExit(f"Import refused: {exc}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    for w in warnings:
        print(f"Warning: {w}")
    with worker.connect_repository() as conn:
        hc.print_summary(conn, health_check_id)
        if args.report:
            from repository.report.health_check_report import write_report
            path = write_report(conn, health_check_id, args.report)
            print(f"\nReport: {path.resolve()}")


if __name__ == "__main__":
    main()
