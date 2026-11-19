"""Define the PostgreSQL systems Keystone checks, without SQL.

    python -m repository.tools.target add-server  --name NAME --environment ENV --host HOST --user USER
    python -m repository.tools.target add-cluster --name NAME --environment ENV --host ENTRY --user USER
    python -m repository.tools.target add-member  --cluster NAME --name NAME --host HOST --user USER
    python -m repository.tools.target list
    python -m repository.tools.target set-password --name NAME

The password is asked without echo, tried against the server and only then
encrypted (KEYSTONE_MASTER_KEY) and written: a wrong password, port or
pg_hba line stops the command before anything is stored.

A single server is stored as a SYSTEM with one NODE, as clusters and offline
import; the user never names the node (ADR: V069, Installation Guide). The
word "node" is not used by the command: a cluster has members.
"""

import argparse
import getpass
import sys

import psycopg
from psycopg.rows import dict_row

from repository.common.credentials import encrypt_credential
from repository.worker import worker


PROVIDER = "PostgreSQL"
APPLICATION_NAME = "Keystone target check"


class TargetError(SystemExit):
    """A command that cannot go on: ends with the message (exit code 1), nothing written."""


# ----------------------------------------------------------------------------- lookups

def top_level(conn, name):
    """An active system, or a server with no system, by name (any case) or by id."""
    if name.isdigit():
        row = conn.execute(
            "SELECT * FROM keystone.target WHERE target_id = %s AND is_active "
            "AND parent_target_id IS NULL", (int(name),)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM keystone.target WHERE lower(name) = lower(%s) AND is_active "
            "AND parent_target_id IS NULL", (name,)).fetchone()
    if row is None:
        known = conn.execute(
            "SELECT name FROM keystone.target WHERE is_active AND parent_target_id IS NULL "
            "ORDER BY lower(name)").fetchall()
        names = ", ".join(r["name"] for r in known) or "none defined yet"
        raise TargetError(f"There is no system named {name}. Systems: {names}.")
    return row


def name_taken(conn, name):
    row = conn.execute(
        "SELECT target_id FROM keystone.target WHERE lower(name) = lower(%s) AND is_active "
        "AND parent_target_id IS NULL", (name,)).fetchone()
    if row:
        raise TargetError(f"A system named {name} already exists (target {row['target_id']}). "
                          "Choose another name, or use set-password to change its password.")


def member_name_taken(conn, system_id, name):
    row = conn.execute(
        "SELECT target_id FROM keystone.target WHERE parent_target_id = %s AND is_active "
        "AND lower(name) = lower(%s)", (system_id, name)).fetchone()
    if row:
        raise TargetError(f"The cluster already has a member named {name} (target {row['target_id']}).")


def address_taken(conn, host, port):
    row = conn.execute(
        """
        SELECT t.target_id, t.name, p.name AS system_name
        FROM keystone.target_connection c
        JOIN keystone.target t ON t.target_id = c.target_id AND t.is_active
        LEFT JOIN keystone.target p ON p.target_id = t.parent_target_id
        WHERE c.is_active AND c.connection_purpose <> 'HOST'
          AND lower(c.host) = lower(%s) AND c.port = %s
        ORDER BY t.target_id LIMIT 1
        """, (host, port)).fetchone()
    if row:
        where = f"{row['system_name']} / {row['name']}" if row["system_name"] else row["name"]
        raise TargetError(f"{host}:{port} is already defined ({where}, target {row['target_id']}).")


# ----------------------------------------------------------------------------- connection

def try_connection(host, port, database, user, password):
    """(version, role) of the server, or TargetError with the server's reason."""
    try:
        with psycopg.connect(host=host, port=port, dbname=database, user=user, password=password,
                             connect_timeout=10, application_name=APPLICATION_NAME,
                             row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT current_setting('server_version') AS version, "
                "pg_is_in_recovery() AS in_recovery").fetchone()
    except psycopg.Error as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise TargetError(
            f"Could not connect to {host}:{port} (database {database}, user {user}): {reason}\n"
            "Nothing was written. Check the password, that the server listens on this address "
            "and port, and that pg_hba.conf allows this user from this machine.")
    return row["version"], "replica" if row["in_recovery"] else "primary"


def ask_password(user, host, port):
    password = getpass.getpass(f"Password of {user} on {host}:{port}: ")
    if not password:
        raise TargetError("No password given. Nothing was written.")
    return password


def checked_credential(args, check=True):
    """Ask, try (unless skipped) and encrypt; the plain password goes no further."""
    password = ask_password(args.user, args.host, args.port)
    if check and not args.skip_connection_test:
        version, role = try_connection(args.host, args.port, args.database, args.user, password)
        print(f"Connected: PostgreSQL {version}, {role}.")
    elif check:
        print("Connection not tested (--skip-connection-test).")
    try:
        return encrypt_credential(password)
    except RuntimeError as exc:
        raise TargetError(f"{exc} Set it for this window (Installation Guide, step 2). Nothing was written.")


def insert_target(conn, name, target_type, environment, parent=None, topology=None):
    return conn.execute(
        "INSERT INTO keystone.target (name, provider, target_type, environment, parent_target_id, topology) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING target_id",
        (name, PROVIDER, target_type, environment, parent, topology)).fetchone()["target_id"]


def insert_connection(conn, target_id, name, args, credential):
    conn.execute(
        "INSERT INTO keystone.target_connection (target_id, connection_name, host, port, database_name, "
        "username, auth_type, credential_data, connection_purpose) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'PASSWORD', %s, 'DIRECT')",
        (target_id, f"{name}-direct", args.host, args.port, args.database, args.user, credential))


# ----------------------------------------------------------------------------- commands

def add_server(conn, args):
    environment = args.environment.upper()
    name_taken(conn, args.name)
    address_taken(conn, args.host, args.port)
    credential = checked_credential(args)
    system_id = insert_target(conn, args.name, "SYSTEM", environment, topology="STANDALONE")
    server_id = insert_target(conn, args.name, "NODE", environment, parent=system_id)
    insert_connection(conn, system_id, args.name, args, credential)
    insert_connection(conn, server_id, args.name, args, credential)
    conn.commit()
    print(f"Added {args.name} (single server, target {system_id}).")
    print(f"Health check: python -m repository.healthcheck.health_check --target {system_id} --report tr")


def add_cluster(conn, args):
    environment = args.environment.upper()
    name_taken(conn, args.name)
    credential = checked_credential(args)
    system_id = insert_target(conn, args.name, "SYSTEM", environment, topology="CLUSTER")
    insert_connection(conn, system_id, args.name, args, credential)
    conn.commit()
    print(f"Added cluster {args.name} (target {system_id}), entry point {args.host}:{args.port}.")
    print(f"Next, add each of its servers: python -m repository.tools.target add-member "
          f"--cluster {args.name} --name <server> --host <address> --user {args.user}")


def add_member(conn, args):
    system = top_level(conn, args.cluster)
    if system["target_type"] != "SYSTEM":
        raise TargetError(f"{system['name']} is a single server defined without a system; "
                          "it cannot have members.")
    if system["topology"] != "CLUSTER":
        kind = "a single server" if system["topology"] == "STANDALONE" else "a system of unknown kind"
        raise TargetError(f"{system['name']} is defined as {kind}, not a cluster: members can be added "
                          "only to a cluster. Nothing was written.")
    member_name_taken(conn, system["target_id"], args.name)
    address_taken(conn, args.host, args.port)
    credential = checked_credential(args)
    member_id = insert_target(conn, args.name, "NODE", system["environment"], parent=system["target_id"])
    insert_connection(conn, member_id, args.name, args, credential)
    conn.commit()
    print(f"Added {args.name} to cluster {system['name']} (target {member_id}).")


def list_targets(conn, args):
    rows = conn.execute(
        """
        SELECT t.target_id, t.name, t.target_type, t.topology, t.environment, t.parent_target_id,
               p.name AS system_name,
               (SELECT c.host || ':' || coalesce(c.port::text, '') || ' ' || coalesce(c.username, '')
                FROM keystone.target_connection c
                WHERE c.target_id = t.target_id AND c.is_active AND c.connection_purpose <> 'HOST'
                ORDER BY c.connection_id LIMIT 1) AS connection
        FROM keystone.target t
        LEFT JOIN keystone.target p ON p.target_id = t.parent_target_id
        WHERE t.is_active
        ORDER BY lower(coalesce(p.name, t.name)), t.parent_target_id NULLS FIRST, t.target_id
        """).fetchall()
    standalone = {r["target_id"] for r in rows if r["topology"] == "STANDALONE"}
    lines = []
    for r in rows:
        if r["parent_target_id"] in standalone:
            continue                                  # the single server's own entry: never shown
        if r["topology"] == "STANDALONE":
            kind = "single server"
        elif r["topology"] == "CLUSTER":
            kind = "cluster"
        elif r["target_type"] == "NODE" and r["parent_target_id"] is None:
            kind = "single server"
        elif r["target_type"] == "NODE":
            kind = f"  member of {r['system_name']}"
        else:
            kind = "system"
        lines.append((str(r["target_id"]), r["name"], kind, r["environment"],
                       r["connection"] or "no connection"))
    if not lines:
        print("No targets defined. Add one with add-server or add-cluster.")
        return
    header = ("ID", "Name", "Kind", "Environment", "Connection")
    widths = [max(len(x[i]) for x in lines + [header]) for i in range(len(header))]
    for line in [header] + lines:
        print("  ".join(v.ljust(w) for v, w in zip(line, widths)).rstrip())


def set_password(conn, args):
    target = top_level(conn, args.name)
    connections = conn.execute(
        """
        SELECT c.connection_id, c.host, c.port, c.database_name, c.username
        FROM keystone.target_connection c JOIN keystone.target t ON t.target_id = c.target_id
        WHERE c.is_active AND t.is_active AND c.connection_purpose <> 'HOST'
          AND (t.target_id = %s OR t.parent_target_id = %s)
        ORDER BY c.connection_id
        """, (target["target_id"], target["target_id"])).fetchall()
    if args.user:
        connections = [c for c in connections if c["username"] == args.user]
    if not connections:
        raise TargetError(f"{target['name']} has no database connection"
                          + (f" with user {args.user}." if args.user else "."))
    users = sorted({c["username"] for c in connections})
    if len(users) > 1:
        raise TargetError(f"{target['name']} connects as several users ({', '.join(users)}); "
                          "give the one whose password changed with --user.")
    password = ask_password(users[0], connections[0]["host"], connections[0]["port"])
    if not args.skip_connection_test:
        tried = set()
        for c in connections:
            address = (c["host"].lower(), c["port"], c["database_name"])
            if address not in tried:
                tried.add(address)
                version, role = try_connection(c["host"], c["port"], c["database_name"],
                                               c["username"], password)
                print(f"Connected to {c['host']}:{c['port']}: PostgreSQL {version}, {role}.")
    try:
        credential = encrypt_credential(password)
    except RuntimeError as exc:
        raise TargetError(f"{exc} Set it for this window (Installation Guide, step 2). Nothing was written.")
    conn.execute("UPDATE keystone.target_connection SET credential_data = %s WHERE connection_id = ANY(%s)",
                 (credential, [c["connection_id"] for c in connections]))
    conn.commit()
    print(f"Password of {users[0]} changed on {len(connections)} connection(s) of {target['name']}.")


# ----------------------------------------------------------------------------- main

def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m repository.tools.target",
        description="Define the PostgreSQL systems Keystone checks. Passwords are asked, tried "
                    "and stored encrypted; nothing is written when a step fails.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    def connection_options(p, environment=True):
        if environment:
            p.add_argument("--environment", required=True, help="PROD, TEST, LAB …")
        p.add_argument("--host", required=True, help="address Keystone connects to")
        p.add_argument("--port", type=int, default=5432)
        p.add_argument("--database", default="postgres", help="database Keystone connects to (default postgres)")
        p.add_argument("--user", required=True, help="monitoring role, for example keystone_monitor")
        p.add_argument("--skip-connection-test", action="store_true",
                       help="store without trying (the server is not reachable from this machine)")

    p = commands.add_parser("add-server", help="a single PostgreSQL server")
    p.add_argument("--name", required=True, help="name shown in reports")
    connection_options(p)
    p.set_defaults(handler=add_server)

    p = commands.add_parser("add-cluster", help="a cluster (Patroni, primary + replicas): its entry point")
    p.add_argument("--name", required=True, help="name shown in reports")
    connection_options(p)
    p.set_defaults(handler=add_cluster)

    p = commands.add_parser("add-member", help="a server of a cluster added with add-cluster")
    p.add_argument("--cluster", required=True, help="cluster name (or id)")
    p.add_argument("--name", required=True, help="server name shown in reports")
    connection_options(p, environment=False)
    p.set_defaults(handler=add_member)

    p = commands.add_parser("list", help="defined systems and servers, without passwords")
    p.set_defaults(handler=list_targets)

    p = commands.add_parser("set-password", help="a monitoring password changed on the server")
    p.add_argument("--name", required=True, help="system or server name (or id)")
    p.add_argument("--user", help="only connections of this user")
    p.add_argument("--skip-connection-test", action="store_true")
    p.set_defaults(handler=set_password)
    return parser


def main(argv=None, connect=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "port", None) is not None and not 1 <= args.port <= 65535:
        raise TargetError(f"Port {args.port} is not a valid port.")
    with (connect or worker.connect_repository)() as conn:
        try:
            args.handler(conn, args)
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            raise TargetError("Another target with this name was added at the same moment. Nothing was written.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled. Nothing was written.", file=sys.stderr)
        raise SystemExit(1)
