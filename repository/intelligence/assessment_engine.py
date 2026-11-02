# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------
import argparse
import json
import logging
import os
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb
from psycopg.rows import dict_row

from repository.common.logging_config import configure_logging, get_logger


# Console + log file + event_log (ADR-0014). Unconfigured: WARNING+ to stderr.
logger = get_logger("assessment_engine")


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
REPOSITORY_CONFIG = {
    "host": os.getenv("KEYSTONE_REPOSITORY_HOST", "localhost"),
    "port": int(os.getenv("KEYSTONE_REPOSITORY_PORT", "5432")),
    "dbname": os.getenv("KEYSTONE_REPOSITORY_DB", "keystone_lab"),
    "user": os.getenv("KEYSTONE_REPOSITORY_USER", "postgres"),
    "password": os.getenv("KEYSTONE_REPOSITORY_PASSWORD"),
}


# -----------------------------------------------------------------------------
# Repository Connection
# -----------------------------------------------------------------------------
def connect_repository():
    return psycopg.connect(
        **REPOSITORY_CONFIG,
        row_factory=dict_row,
    )


# -----------------------------------------------------------------------------
# Dictionary
# -----------------------------------------------------------------------------
def load_assessment(conn, assessment_key):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                assessment_id,
                assessment_key,
                name,
                provider,
                description
            FROM keystone.assessment_definition
            WHERE assessment_key = %s
              AND is_enabled = TRUE
            """,
            (assessment_key,),
        )

        assessment = cur.fetchone()

    if assessment is None:
        raise RuntimeError(
            f"Assessment definition not found or disabled: {assessment_key}"
        )

    return assessment


def load_rules(conn, assessment_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                rule_id,
                rule_key,
                name,
                description,
                evidence_source,
                default_severity,
                finding_template,
                recommendation
            FROM keystone.rule_definition
            WHERE assessment_id = %s
              AND is_enabled = TRUE
            ORDER BY rule_id
            """,
            (assessment_id,),
        )

        return cur.fetchall()


def load_thresholds(conn, rule_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                threshold_id,
                severity,
                threshold_value,
                threshold_unit
            FROM keystone.rule_threshold
            WHERE rule_id = %s
            -- Order is for readable output only; evaluators select the
            -- reached threshold through match_threshold(), independent of it.
            ORDER BY threshold_value DESC
            """,
            (rule_id,),
        )

        return cur.fetchall()

def load_evidence_requirements(conn, rule_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                requirement_id,
                evidence_source,
                is_required,
                max_age_seconds
            FROM keystone.rule_evidence_requirement
            WHERE rule_id = %s
            ORDER BY requirement_id
            """,
            (rule_id,),
        )

        return cur.fetchall()

# -----------------------------------------------------------------------------
# Assessment Persistence
# -----------------------------------------------------------------------------
def create_assessment_run(
    conn,
    assessment_id,
    target_id,
    started_at,
    scheduled_at=None,
    health_check_id=None,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO keystone.assessment_run
            (
                assessment_id,
                target_id,
                started_at,
                scheduled_at,
                health_check_id,
                status
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                'RUNNING'
            )
            RETURNING assessment_run_id
            """,
            (
                assessment_id,
                target_id,
                started_at,
                scheduled_at,
                health_check_id,
            ),
        )

        return cur.fetchone()["assessment_run_id"]


def complete_assessment_run(
    conn,
    assessment_run_id,
    status,
    status_message=None,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE keystone.assessment_run
            SET
                finished_at = clock_timestamp(),
                status = %s,
                status_message = %s
            WHERE assessment_run_id = %s
            """,
            (
                status,
                status_message,
                assessment_run_id,
            ),
        )


def insert_assessment_result(
    conn,
    assessment_run_id,
    rule,
    outcome,
    max_severity,
    finding_count,
    reason,
    evaluated_at,
    thresholds=None,
    parameters=None,
):
    """Persist the outcome of one rule in one run (ADR-0014), with the thresholds and parameters used."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO keystone.assessment_result
            (
                assessment_run_id,
                rule_id,
                outcome,
                max_severity,
                finding_count,
                reason,
                evaluated_at,
                thresholds_used,
                parameters_used
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                assessment_run_id,
                rule["rule_id"],
                outcome,
                max_severity,
                finding_count,
                reason,
                evaluated_at,
                Jsonb(thresholds_snapshot(thresholds)) if thresholds is not None else None,
                Jsonb(parameters) if parameters else None,
            ),
        )


def load_parameters(conn, rule_id):
    """{parameter_key: {"value", "unit"}}: rule preconditions and limits besides the severity thresholds."""
    rows = conn.execute(
        "SELECT parameter_key, parameter_value, parameter_unit FROM keystone.rule_parameter "
        "WHERE rule_id = %s ORDER BY parameter_key", (rule_id,)).fetchall()
    return {r["parameter_key"]: {"value": float(r["parameter_value"]), "unit": r["parameter_unit"]}
            for r in rows}


def parameter(rule, key):
    """A parameter value of the rule; a missing parameter is a Dictionary error."""
    try:
        return rule["parameters"][key]["value"]
    except KeyError:
        raise RuntimeError(f"Rule {rule['rule_key']} has no parameter {key}.") from None


def thresholds_snapshot(thresholds):
    """Thresholds as evaluated, so reports stay correct after the Dictionary changes."""
    return [
        {"severity": t["severity"], "value": float(t["threshold_value"]),
         "unit": t["threshold_unit"]}
        for t in thresholds
    ]

def insert_finding(
    conn,
    assessment_run_id,
    rule,
    finding,
):
    finding_text = rule["finding_template"].format(
        **finding["template_values"]
    )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO keystone.finding
            (
                assessment_run_id,
                rule_id,
                severity,
                title,
                finding_text,
                recommendation,
                observed_value,
                observed_unit,
                subject_type,
                subject_identifier,
                details,
                template_values
            )
            VALUES
            (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING finding_id
            """,
            (
                assessment_run_id,
                rule["rule_id"],
                finding["severity"],
                rule["name"],
                finding_text,
                rule["recommendation"],
                finding["observed_value"],
                finding["observed_unit"],
                finding["subject_type"],
                finding["subject_identifier"],
                Jsonb(finding["details"]) if finding.get("details") else None,
                # Kept so reports can phrase the finding in their own language.
                Jsonb(finding["template_values"]),
            ),
        )

        return cur.fetchone()["finding_id"]

# -----------------------------------------------------------------------------
# Evidence
# -----------------------------------------------------------------------------
def load_latest_activity_snapshot(conn, target_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                snapshot_id,
                target_id,
                captured_at,
                database_name,
                pid,
                user_name,
                application_name,
                host(client_addr) AS client_addr,
                client_hostname,
                transaction_start,
                query_start,
                state_change,
                wait_event_type,
                wait_event,
                state,
                query_text,
                backend_type
            FROM postgresql.activity_snapshot
            WHERE target_id = %s
              AND captured_at =
              (
                  SELECT MAX(captured_at)
                  FROM postgresql.activity_snapshot
                  WHERE target_id = %s
              )
            ORDER BY pid
            """,
            (target_id, target_id),
        )

        return cur.fetchall()


def load_latest_transaction_wraparound_snapshot(conn, target_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                snapshot_id,
                target_id,
                captured_at,
                database_oid,
                database_name,
                frozen_xid,
                xid_age,
                min_mxid,
                mxid_age
            FROM postgresql.transaction_wraparound_snapshot
            WHERE target_id = %s
              AND captured_at =
              (
                  SELECT MAX(captured_at)
                  FROM postgresql.transaction_wraparound_snapshot
                  WHERE target_id = %s
              )
            ORDER BY database_name
            """,
            (target_id, target_id),
        )

        return cur.fetchall()


def load_latest_replication_slot_snapshot(conn, target_id):
    """Latest PG_REPLICATION_SLOTS: the SYSTEM row (slot count) and the slots captured with it."""
    system = conn.execute(
        """
        SELECT 'SYSTEM' AS record_type, snapshot_id, target_id, captured_at, slot_count
        FROM postgresql.replication_slot_status_snapshot
        WHERE target_id = %s ORDER BY captured_at DESC LIMIT 1
        """, (target_id,)).fetchone()
    if system is None:
        return []
    slots = conn.execute(
        """
        SELECT 'SLOT' AS record_type, snapshot_id, target_id, captured_at, slot_name, plugin,
               slot_type, database_name, temporary, active, active_pid, slot_xmin, catalog_xmin,
               restart_lsn, confirmed_flush_lsn, wal_status, safe_wal_size, two_phase,
               conflicting, invalidation_reason, failover
        FROM postgresql.replication_slot_snapshot
        WHERE target_id = %s AND captured_at = %s
        ORDER BY slot_name
        """, (target_id, system["captured_at"])).fetchall()
    return [system] + slots


def load_latest_connection_activity_snapshot(conn, target_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                snapshot_id,
                target_id,
                captured_at,
                total_client_connections,
                active_connections,
                idle_connections,
                idle_in_transaction_connections,
                idle_in_transaction_aborted_connections,
                oldest_idle_state_change,
                oldest_idle_in_transaction_state_change,
                oldest_idle_in_transaction_aborted_state_change
            FROM postgresql.connection_activity_snapshot
            WHERE target_id = %s
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (target_id,),
        )

        row = cur.fetchone()

    if row is None:
        return []

    return [row]


def node_target_ids(conn, target_id):
    """NODE-scoped evidence lives on nodes: the target itself if a NODE, else its active NODE children."""
    rows = conn.execute(
        "SELECT target_id FROM keystone.target WHERE (target_id = %s AND target_type = 'NODE') "
        "OR (parent_target_id = %s AND target_type = 'NODE' AND is_active) ORDER BY target_id",
        (target_id, target_id)).fetchall()
    return [r["target_id"] for r in rows]


def load_latest_replication_status(conn, target_id):
    """Latest PG_REPLICATION_STATUS: the SYSTEM row and the REPLICA rows captured with it."""
    system = conn.execute(
        """
        SELECT 'SYSTEM' AS record_type, snapshot_id, target_id, captured_at, current_wal_lsn,
               connected_replica_count, synchronous_standby_names
        FROM postgresql.replication_status_snapshot
        WHERE target_id = %s ORDER BY captured_at DESC LIMIT 1
        """, (target_id,)).fetchone()
    if system is None:
        return []
    replicas = conn.execute(
        """
        SELECT 'REPLICA' AS record_type, snapshot_id, target_id, captured_at, application_name,
               host(client_addr) AS client_addr, state, sync_state,
               EXTRACT(EPOCH FROM replay_lag)::float AS replay_lag_seconds,
               pg_wal_lsn_diff(current_wal_lsn, replay_lsn)::bigint AS replay_lag_bytes,
               backend_start, reply_time
        FROM postgresql.replica_status_snapshot
        WHERE target_id = %s AND captured_at = %s
        ORDER BY application_name, client_addr
        """, (target_id, system["captured_at"])).fetchall()
    return [system] + replicas


def load_instance_inventory(conn, target_id):
    """Current instance inventory per node (PG_INSTANCE_INVENTORY); one row per node."""
    return conn.execute(
        """
        SELECT ii.target_id, t.name AS node_name, ii.last_collected_at AS captured_at,
               ii.server_address, ii.server_port, ii.in_recovery, ii.server_version,
               ii.postmaster_start_time
        FROM postgresql.instance_inventory ii
        JOIN keystone.target t ON t.target_id = ii.target_id
        WHERE ii.target_id = ANY(%s)
        ORDER BY ii.target_id
        """, (node_target_ids(conn, target_id),)).fetchall()


def load_latest_vacuum_analyze_snapshot(conn, target_id):
    """Latest PG_VACUUM_ANALYZE snapshot per database of the target (one row per table)."""
    return conn.execute(
        """
        SELECT v.snapshot_id, v.target_id, v.captured_at, v.database_name, v.schema_name,
               v.object_name, v.is_partition, v.n_live_tup, v.n_dead_tup, v.n_mod_since_analyze,
               v.last_vacuum, v.last_autovacuum, v.last_analyze, v.last_autoanalyze,
               v.autovacuum_count, v.autoanalyze_count
        FROM postgresql.vacuum_analyze_snapshot v
        JOIN (
            SELECT database_name, max(captured_at) AS captured_at
            FROM postgresql.vacuum_analyze_snapshot WHERE target_id = %s GROUP BY database_name
        ) latest ON latest.database_name = v.database_name AND latest.captured_at = v.captured_at
        WHERE v.target_id = %s
        ORDER BY v.database_name, v.schema_name, v.object_name
        """, (target_id, target_id)).fetchall()


def load_latest_storage_snapshot(conn, target_id):
    """Latest filesystem capacity per node (PG_HOST_SNAPSHOT)."""
    return conn.execute(
        """
        SELECT s.snapshot_id, s.target_id, t.name AS node_name, s.captured_at,
               s.device, s.mount_point, s.total_bytes, s.used_bytes, s.available_bytes
        FROM keystone.target t
        JOIN LATERAL (
            SELECT max(captured_at) AS captured_at FROM postgresql.storage_snapshot
            WHERE target_id = t.target_id
        ) last ON last.captured_at IS NOT NULL
        JOIN postgresql.storage_snapshot s
            ON s.target_id = t.target_id AND s.captured_at = last.captured_at
        WHERE t.target_id = ANY(%s)
        ORDER BY s.target_id, s.mount_point
        """, (node_target_ids(conn, target_id),)).fetchall()


def load_latest_configuration_snapshot(conn, target_id):
    """Latest pg_settings snapshot per node (PG_CONFIGURATION_SNAPSHOT)."""
    return conn.execute(
        """
        SELECT c.target_id, t.name AS node_name, c.captured_at,
               c.setting_name, c.setting_value, c.unit, c.source, c.pending_restart
        FROM keystone.target t
        JOIN LATERAL (
            SELECT max(captured_at) AS captured_at FROM postgresql.configuration_snapshot
            WHERE target_id = t.target_id
        ) last ON last.captured_at IS NOT NULL
        JOIN postgresql.configuration_snapshot c
            ON c.target_id = t.target_id AND c.captured_at = last.captured_at
        WHERE t.target_id = ANY(%s)
        ORDER BY c.target_id, c.setting_name
        """, (node_target_ids(conn, target_id),)).fetchall()


def load_latest_wal_status(conn, target_id):
    """Latest PG_WAL_STATUS per node: archiver statistics, timeline and when it began."""
    return conn.execute(
        """
        SELECT w.snapshot_id, w.target_id, t.name AS node_name, w.captured_at, w.in_recovery,
               w.archive_mode, w.timeline_id, w.timeline_history_file, w.timeline_started_at,
               w.archived_count, w.last_archived_wal, w.last_archived_time, w.failed_count,
               w.last_failed_wal, w.last_failed_time, w.stats_reset
        FROM keystone.target t
        JOIN LATERAL (
            SELECT * FROM postgresql.wal_status_snapshot s
            WHERE s.target_id = t.target_id ORDER BY s.captured_at DESC LIMIT 1
        ) w ON TRUE
        WHERE t.target_id = ANY(%s)
        ORDER BY w.target_id
        """, (node_target_ids(conn, target_id),)).fetchall()


def load_latest_prepared_transactions(conn, target_id):
    """Latest PG_PREPARED_TRANSACTIONS: the SYSTEM row and the transactions captured with it."""
    system = conn.execute(
        """
        SELECT 'SYSTEM' AS record_type, snapshot_id, target_id, captured_at,
               max_prepared_transactions, prepared_count
        FROM postgresql.prepared_transaction_status_snapshot
        WHERE target_id = %s ORDER BY captured_at DESC LIMIT 1
        """, (target_id,)).fetchone()
    if system is None:
        return []
    transactions = conn.execute(
        """
        SELECT 'TRANSACTION' AS record_type, snapshot_id, target_id, captured_at,
               transaction_id::text AS transaction_id, gid, prepared_at, owner, database_name
        FROM postgresql.prepared_transaction_snapshot
        WHERE target_id = %s AND captured_at = %s
        ORDER BY prepared_at
        """, (target_id, system["captured_at"])).fetchall()
    return [system] + transactions


def load_latest_index_usage(conn, target_id):
    """Latest PG_INDEX_USAGE per node and database, plus a NODES row naming every node expected."""
    nodes = conn.execute(
        "SELECT target_id, name FROM keystone.target WHERE target_id = ANY(%s) ORDER BY target_id",
        (node_target_ids(conn, target_id),)).fetchall()
    rows = conn.execute(
        """
        SELECT u.snapshot_id, u.target_id, t.name AS node_name, u.captured_at, u.record_type,
               u.database_name, u.in_recovery, u.stats_since, u.stats_since_start, u.schema_name,
               u.table_name, u.index_name, u.idx_scan, u.index_size_bytes, u.is_valid, u.is_unique,
               u.constraint_type, u.being_built, u.extension_owned
        FROM postgresql.index_usage_snapshot u
        JOIN keystone.target t ON t.target_id = u.target_id
        JOIN (
            SELECT target_id, database_name, max(captured_at) AS captured_at
            FROM postgresql.index_usage_snapshot
            WHERE target_id = ANY(%s) AND record_type = 'DATABASE'
            GROUP BY target_id, database_name
        ) latest ON latest.target_id = u.target_id AND latest.database_name = u.database_name
                AND latest.captured_at = u.captured_at
        ORDER BY u.target_id, u.database_name, u.record_type, u.schema_name, u.index_name
        """, ([n["target_id"] for n in nodes],)).fetchall()
    if not rows:
        return []
    # Expected nodes; its time is the newest collection so it is as fresh as the data.
    marker = {"record_type": "NODES", "target_id": target_id,
              "captured_at": max(r["captured_at"] for r in rows),
              "nodes": [{"target_id": n["target_id"], "name": n["name"]} for n in nodes]}
    return [marker] + rows


def load_latest_schema_privileges(conn, target_id):
    """Latest PG_SCHEMA_PRIVILEGES per database of the target."""
    return conn.execute(
        """
        SELECT s.snapshot_id, s.target_id, s.captured_at, s.record_type, s.database_name,
               s.schema_name, s.schema_owner, s.public_usage, s.public_create
        FROM postgresql.schema_privilege_snapshot s
        JOIN (
            SELECT database_name, max(captured_at) AS captured_at
            FROM postgresql.schema_privilege_snapshot
            WHERE target_id = %s AND record_type = 'DATABASE' GROUP BY database_name
        ) latest ON latest.database_name = s.database_name AND latest.captured_at = s.captured_at
        WHERE s.target_id = %s
        ORDER BY s.database_name, s.record_type, s.schema_name
        """, (target_id, target_id)).fetchall()


def load_latest_roles(conn, target_id):
    """Latest PG_ROLES snapshot of the target."""
    return conn.execute(
        """
        SELECT snapshot_id, target_id, captured_at, role_oid, role_name, can_login, is_superuser,
               can_create_role, can_create_db, is_replication, bypass_rls, valid_until
        FROM postgresql.role_snapshot
        WHERE target_id = %s
          AND captured_at = (SELECT max(captured_at) FROM postgresql.role_snapshot WHERE target_id = %s)
        ORDER BY role_name
        """, (target_id, target_id)).fetchall()


def load_latest_sequence_capacity(conn, target_id):
    """Latest PG_SEQUENCE_CAPACITY per database of the target."""
    return conn.execute(
        """
        SELECT s.snapshot_id, s.target_id, s.captured_at, s.record_type, s.database_name,
               s.schema_name, s.sequence_name, s.data_type, s.min_value, s.max_value,
               s.increment_by, s.is_cycle, s.is_readable, s.last_value, s.table_name,
               s.column_name, s.column_type
        FROM postgresql.sequence_capacity_snapshot s
        JOIN (
            SELECT database_name, max(captured_at) AS captured_at
            FROM postgresql.sequence_capacity_snapshot
            WHERE target_id = %s AND record_type = 'DATABASE' GROUP BY database_name
        ) latest ON latest.database_name = s.database_name AND latest.captured_at = s.captured_at
        WHERE s.target_id = %s
        ORDER BY s.database_name, s.record_type, s.schema_name, s.sequence_name
        """, (target_id, target_id)).fetchall()


# -----------------------------------------------------------------------------
# Rule Evaluation
# -----------------------------------------------------------------------------
# Used only to break ties between thresholds with the same value.
SEVERITY_RANK = {"INFO": 1, "WARNING": 2, "CRITICAL": 3}


def match_threshold(observed_value, thresholds, unit):
    """Highest threshold reached (value >= threshold, same unit), or None.

    Independent of the order thresholds arrive in.
    """
    reached = [
        threshold
        for threshold in thresholds
        if threshold["threshold_unit"] == unit
        and observed_value >= float(threshold["threshold_value"])
    ]

    if not reached:
        return None

    return max(
        reached,
        key=lambda threshold: (
            threshold["threshold_value"],
            SEVERITY_RANK.get(threshold["severity"], 0),
        ),
    )


# Last query is trimmed: enough to recognise the work, less customer data.
QUERY_PREVIEW_CHARS = 200


def iso(value):
    return value.isoformat() if value is not None else None


def session_details(row):
    """Who / where of a session for the finding (shown in technical reports only)."""
    query = " ".join((row.get("query_text") or "").split())
    if len(query) > QUERY_PREVIEW_CHARS:
        query = query[:QUERY_PREVIEW_CHARS] + "..."
    details = {
        "database": row.get("database_name"),
        "user": row.get("user_name"),
        "application": row.get("application_name"),
        "client_addr": row.get("client_addr"),
        "client_hostname": row.get("client_hostname"),
        "state": row.get("state"),
        "last_query": query or None,
        "transaction_start": iso(row.get("transaction_start")),
        "state_change": iso(row.get("state_change")),
        "captured_at": iso(row.get("captured_at")),
    }
    return {key: value for key, value in details.items() if value not in (None, "")}


def evaluate_long_idle_transaction(rows, rule, thresholds):
    """PG-TRAN-001: how long a session has been idle in a transaction.

    Measured from state_change, not transaction_start (age is PG-TRAN-003).
    """
    findings = []

    for row in rows:
        if row["backend_type"] != "client backend":
            continue

        if row["state"] != "idle in transaction":
            continue

        if row["state_change"] is None:
            continue

        duration_seconds = (
            row["captured_at"] - row["state_change"]
        ).total_seconds()

        matched_threshold = match_threshold(
            duration_seconds,
            thresholds,
            "SECOND",
        )

        if matched_threshold is None:
            continue

        findings.append(
            {
                "pid": row["pid"],
                "duration_seconds": duration_seconds,
                "severity": matched_threshold["severity"],
                "snapshot_id": row["snapshot_id"],
                "template_values": {
                    "pid": row["pid"],
                    "duration_seconds": f"{duration_seconds:.1f}",
                },
                "observed_value": duration_seconds,
                "observed_unit": "SECOND",
                "subject_type": "SESSION",
                "subject_identifier": str(row["pid"]),
                "details": session_details(row),
            }
        )

    return findings



# Top-level failed transactions have already released their snapshot and
# locks; they are reported by PG-CONN-001 and excluded from transaction age.
EXCLUDED_LONG_RUNNING_STATES = {"idle in transaction (aborted)"}


def evaluate_long_running_transaction(rows, rule, thresholds):
    """PG-TRAN-003: transaction age in any non-aborted state.

    A long idle transaction may also match PG-TRAN-001; that is intended.
    """
    findings = []

    for row in rows:
        if row["backend_type"] != "client backend":
            continue

        if row["transaction_start"] is None:
            continue

        if row["state"] in EXCLUDED_LONG_RUNNING_STATES:
            continue

        duration_seconds = (
            row["captured_at"] - row["transaction_start"]
        ).total_seconds()

        matched_threshold = match_threshold(
            duration_seconds,
            thresholds,
            "SECOND",
        )

        if matched_threshold is None:
            continue

        findings.append(
            {
                "pid": row["pid"],
                "duration_seconds": duration_seconds,
                "severity": matched_threshold["severity"],
                "snapshot_id": row["snapshot_id"],
                "template_values": {
                    "pid": row["pid"],
                    "duration_seconds": f"{duration_seconds:.1f}",
                    "state": row["state"],
                },
                "observed_value": duration_seconds,
                "observed_unit": "SECOND",
                "subject_type": "SESSION",
                "subject_identifier": str(row["pid"]),
                "details": session_details(row),
            }
        )

    return findings

def evaluate_database_mxid_wraparound(rows, rule, thresholds):
    """PG-TRAN-004: per-database MultiXact ID age against absolute thresholds."""
    findings = []
    for row in rows:
        age = row["mxid_age"]
        if age is None:
            continue
        matched_threshold = match_threshold(age, thresholds, "MULTIXACT")
        if matched_threshold is None:
            continue
        findings.append({
            "severity": matched_threshold["severity"],
            "snapshot_id": row["snapshot_id"],
            "template_values": {"database_name": row["database_name"], "mxid_age": age},
            "observed_value": age,
            "observed_unit": "MULTIXACT",
            "subject_type": "DATABASE",
            "subject_identifier": row["database_name"],
            "details": {"database": row["database_name"], "captured_at": iso(row["captured_at"])},
        })
    return findings


def evaluate_database_xid_wraparound(rows, rule, thresholds):
    """PG-TRAN-002: per-database XID age against absolute thresholds."""
    findings = []

    for row in rows:
        xid_age = row["xid_age"]

        matched_threshold = match_threshold(
            xid_age,
            thresholds,
            "TRANSACTION",
        )

        if matched_threshold is None:
            continue

        findings.append(
            {
                "database_name": row["database_name"],
                "xid_age": xid_age,
                "severity": matched_threshold["severity"],
                "snapshot_id": row["snapshot_id"],
                "template_values": {
                    "database_name": row["database_name"],
                    "xid_age": xid_age,
                },
                "observed_value": xid_age,
                "observed_unit": "TRANSACTION",
                "subject_type": "DATABASE",
                "subject_identifier": row["database_name"],
            }
        )

    return findings


def slot_rows(rows):
    """Slot rows of PG_REPLICATION_SLOTS; the SYSTEM row only proves the collection ran."""
    return [r for r in rows if r.get("record_type", "SLOT") == "SLOT"]


def evaluate_replication_slot_wal_retention_pressure(
    rows,
    rule,
    thresholds,
):
    """PG-REP-001: slots with wal_status extended; severity from the rule."""
    findings = []

    for row in slot_rows(rows):
        if row["wal_status"] != "extended":
            continue

        findings.append(
            {
                "slot_name": row["slot_name"],
                "wal_status": row["wal_status"],
                "severity": rule["default_severity"],
                "snapshot_id": row["snapshot_id"],
                "template_values": {
                    "slot_name": row["slot_name"],
                    "wal_status": row["wal_status"],
                },
                "observed_value": None,
                "observed_unit": None,
                "subject_type": "REPLICATION_SLOT",
                "subject_identifier": row["slot_name"],
            }
        )

    return findings


def evaluate_replication_slot_wal_unavailable(
    rows,
    rule,
    thresholds,
):
    """PG-REP-002: slots with wal_status unreserved/lost; severity from the rule."""
    findings = []

    for row in slot_rows(rows):
        if row["wal_status"] not in ("unreserved", "lost"):
            continue

        findings.append(
            {
                "slot_name": row["slot_name"],
                "wal_status": row["wal_status"],
                "severity": rule["default_severity"],
                "snapshot_id": row["snapshot_id"],
                "template_values": {
                    "slot_name": row["slot_name"],
                    "wal_status": row["wal_status"],
                },
                "observed_value": None,
                "observed_unit": None,
                "subject_type": "REPLICATION_SLOT",
                "subject_identifier": row["slot_name"],
            }
        )

    return findings


def evaluate_aborted_idle_transaction_connections(rows, rule, thresholds):
    """PG-CONN-001: count of sessions idle in an aborted transaction."""
    findings = []

    for row in rows:
        connection_count = row["idle_in_transaction_aborted_connections"]

        matched_threshold = match_threshold(
            connection_count,
            thresholds,
            "CONNECTION",
        )

        if matched_threshold is None:
            continue

        findings.append(
            {
                "connection_count": connection_count,
                "severity": matched_threshold["severity"],
                "snapshot_id": row["snapshot_id"],
                "template_values": {
                    "connection_count": connection_count,
                },
                "observed_value": connection_count,
                "observed_unit": "CONNECTION",
                "subject_type": "SYSTEM",
                "subject_identifier": str(row["target_id"]),
            }
        )

    return findings


def usage_percent(used_bytes, available_bytes, total_bytes):
    """Used share of the space PostgreSQL can use, like df's Use%.

    Root-reserved blocks (ext4: 5 %) are not available to the postgres user,
    so used / (used + available) is used when available is known.
    """
    used = used_bytes or 0
    if available_bytes is not None and used + available_bytes > 0:
        return 100 * used / (used + available_bytes)
    return 100 * used / total_bytes if total_bytes else None


def replica_details(row):
    return {
        "application": row.get("application_name"),
        "client_addr": row.get("client_addr"),
        "state": row.get("state"),
        "sync_state": row.get("sync_state"),
        "wal_behind_bytes": row.get("replay_lag_bytes"),
        "captured_at": iso(row.get("captured_at")),
    }


def replica_label(row):
    return row.get("application_name") or row.get("client_addr") or "?"


SETTING_UNIT_SECONDS = {"ms": 0.001, "s": 1, "min": 60, "h": 3600, "d": 86400}


def setting_seconds(row):
    """A time setting from pg_settings (value in its unit) in seconds; None if not a time."""
    try:
        return float(row["setting_value"]) * SETTING_UNIT_SECONDS[row.get("unit") or "ms"]
    except (KeyError, TypeError, ValueError):
        return None


def intended_apply_delays(evidence):
    """{replica address: recovery_min_apply_delay seconds} from node configuration and inventory."""
    addresses = {n["target_id"]: str(n["server_address"]).split("/")[0]
                 for n in evidence.get("PG_INSTANCE_INVENTORY", []) if n["server_address"]}
    delays = {}
    for row in evidence.get("PG_CONFIGURATION_SNAPSHOT", []):
        if row["setting_name"] == "recovery_min_apply_delay" and row["target_id"] in addresses:
            delays[addresses[row["target_id"]]] = setting_seconds(row) or 0.0
    return delays


def evaluate_replication_lag(evidence, rule, thresholds):
    """PG-REP-003: replay lag in time per connected replica, beyond any intended apply delay.

    replay_lag is NULL when the replica has caught up and the primary is idle: no lag.
    A replica delayed on purpose (recovery_min_apply_delay) is judged on the lag beyond it.
    """
    rows = evidence["PG_REPLICATION_STATUS"] if isinstance(evidence, dict) else evidence
    delays = intended_apply_delays(evidence) if isinstance(evidence, dict) else {}
    inventory = (evidence.get("PG_INSTANCE_INVENTORY") or []) if isinstance(evidence, dict) else []
    if no_replicas(rows, inventory):
        raise NotApplicable("PG_REPLICATION_STATUS", "no_replicas", "The system has no replicas.")
    findings = []
    for row in rows:
        if row["record_type"] != "REPLICA":
            continue
        lag = row["replay_lag_seconds"] or 0.0
        delay = delays.get(str(row["client_addr"] or "").split("/")[0], 0.0)
        excess = max(lag - delay, 0.0)
        matched_threshold = match_threshold(excess, thresholds, "SECOND")
        if matched_threshold is None:
            continue
        # The measured lag stays the observed value; the threshold applies to the part beyond the delay.
        details = replica_details(row)
        delay_note, delay_values = "", {}
        if delay:
            details["apply_delay_seconds"] = delay
            details["beyond_delay_seconds"] = round(excess, 1)
            delay_note = f" ({excess:.1f} seconds beyond its intended apply delay of {delay:g} seconds)"
            # The alternative Dictionary sentence (FINDING_ALT) names the delay.
            delay_values = {"_alt": True, "beyond_seconds": f"{excess:.1f}", "delay_seconds": f"{delay:g}"}
        findings.append(
            {
                "severity": matched_threshold["severity"],
                "snapshot_id": row["snapshot_id"],
                "template_values": {
                    "replica": replica_label(row),
                    "lag_seconds": f"{lag:.1f}",
                    "delay_note": delay_note,
                    **delay_values,
                },
                "observed_value": round(lag, 1),
                "observed_unit": "SECOND",
                "subject_type": "REPLICA",
                "subject_identifier": replica_label(row),
                "details": details,
            }
        )
    return findings


def evaluate_replica_not_streaming(evidence, rule, thresholds):
    """PG-REP-004: every node known as a replica must stream from the primary.

    Known replicas come from the instance inventory (in recovery); they are
    matched to pg_stat_replication by address, by count when an address is missing.
    """
    status = evidence["PG_REPLICATION_STATUS"]
    replicas = [r for r in status if r["record_type"] == "REPLICA"]
    expected = [n for n in evidence["PG_INSTANCE_INVENTORY"] if n["in_recovery"]]
    if no_replicas(status, evidence["PG_INSTANCE_INVENTORY"]):
        raise NotApplicable("PG_REPLICATION_STATUS", "no_replicas", "The system has no replicas.")
    findings = []

    def finding(severity, subject, values, details):
        return {"severity": severity, "snapshot_id": None, "template_values": values,
                "observed_value": None, "observed_unit": None, "subject_type": "REPLICA",
                "subject_identifier": subject, "details": details}

    def address(value):
        return str(value).split("/")[0] if value else None

    connected = {address(r["client_addr"]) for r in replicas if r["client_addr"]}
    streaming = [r for r in replicas if r["state"] == "streaming"]
    # Losing every replica means no failover target at all.
    severity = "CRITICAL" if expected and not streaming else rule["default_severity"]
    captured_at = iso(status[0]["captured_at"])
    if all(n["server_address"] for n in expected):
        for n in expected:
            if address(n["server_address"]) not in connected:
                findings.append(finding(
                    severity, n["node_name"],
                    {"replica": n["node_name"], "state": "not connected"},
                    {"node": n["node_name"], "client_addr": address(n["server_address"]),
                     "state": "not connected", "captured_at": captured_at}))
    elif len(replicas) < len(expected):
        count = f"{len(expected) - len(replicas)} of {len(expected)} replicas"
        findings.append(finding(severity, count, {"replica": count, "state": "not connected"},
                                {"state": "not connected", "captured_at": captured_at}))
    for r in replicas:
        if r["state"] != "streaming":
            findings.append(finding(
                severity, replica_label(r),
                {"replica": replica_label(r), "state": r["state"]}, replica_details(r)))
    return findings


def evaluate_inactive_replication_slot(rows, rule, thresholds):
    """PG-REP-005: permanent slots nobody is using; they retain WAL and may hold xmin."""
    findings = []
    for row in slot_rows(rows):
        if row["active"] or row["temporary"]:
            continue
        findings.append(
            {
                "severity": rule["default_severity"],
                "snapshot_id": row["snapshot_id"],
                "template_values": {
                    "slot_name": row["slot_name"],
                    "slot_type": row["slot_type"],
                },
                "observed_value": None,
                "observed_unit": None,
                "subject_type": "REPLICATION_SLOT",
                "subject_identifier": row["slot_name"],
                "details": {
                    "slot_name": row["slot_name"],
                    "slot_type": row["slot_type"],
                    "database": row["database_name"],
                    "wal_status": row["wal_status"],
                    "captured_at": iso(row["captured_at"]),
                },
            }
        )
    return findings


def evaluate_sync_standby_missing(rows, rule, thresholds):
    """PG-REP-006: synchronous replication configured but no standby is synchronous; commits wait."""
    system = next((r for r in rows if r["record_type"] == "SYSTEM"), None)
    names = (system or {}).get("synchronous_standby_names")
    if not names or not names.strip():
        return []
    if any(r["record_type"] == "REPLICA" and r["sync_state"] in ("sync", "quorum") for r in rows):
        return []
    return [
        {
            "severity": rule["default_severity"],
            "snapshot_id": system["snapshot_id"],
            "template_values": {"synchronous_standby_names": names},
            "observed_value": None,
            "observed_unit": None,
            "subject_type": "SYSTEM",
            "subject_identifier": str(system["target_id"]),
            "details": {"synchronous_standby_names": names,
                        "captured_at": iso(system["captured_at"])},
        }
    ]


def current_primary(inventory):
    """The node not in recovery with the newest inventory; after a failover the old row may linger."""
    primaries = [n for n in inventory if n["in_recovery"] is False]
    return max(primaries, key=lambda n: n["captured_at"]) if primaries else None


def settings_by_node(rows):
    """{target_id: {setting_name: row}} from configuration snapshot rows."""
    nodes = {}
    for row in rows:
        nodes.setdefault(row["target_id"], {})[row["setting_name"]] = row
    return nodes


def setting_finding(severity, row):
    """A finding about one setting on one node."""
    return {"severity": severity, "snapshot_id": None,
            "template_values": {"node_name": row["node_name"], "setting": row["setting_name"],
                                "value": row["setting_value"]},
            "observed_value": None, "observed_unit": None, "subject_type": "SETTING",
            "subject_identifier": f"{row['node_name']}: {row['setting_name']}",
            "details": {"node": row["node_name"], "setting": row["setting_name"],
                        "value": row["setting_value"], "setting_unit": row.get("unit"),
                        "setting_source": row.get("source"),
                        "captured_at": iso(row.get("captured_at"))}}


def evaluate_pending_restart(rows, rule, thresholds):
    """PG-CONF-001: settings changed in the configuration but waiting for a restart."""
    findings = []
    for row in rows:
        if not row["pending_restart"]:
            continue
        findings.append(setting_finding(rule["default_severity"], row))
    return findings


# Durability settings: value that is unsafe -> severity (conscious choices are WARNING).
UNSAFE_DURABILITY = {
    "fsync": ("off", "CRITICAL"),
    "full_page_writes": ("off", "CRITICAL"),
    "synchronous_commit": ("off", "WARNING"),
}


def evaluate_unsafe_durability(rows, rule, thresholds):
    """PG-CONF-002: settings that trade crash safety for speed, per node."""
    findings = []
    for row in rows:
        unsafe = UNSAFE_DURABILITY.get(row["setting_name"])
        if unsafe is None or row["setting_value"] != unsafe[0]:
            continue
        findings.append(setting_finding(unsafe[1], row))
    return findings


def evaluate_autovacuum_disabled(rows, rule, thresholds):
    """PG-CONF-004: autovacuum off, or track_counts off (autovacuum cannot work without it)."""
    findings = []
    for row in rows:
        if row["setting_name"] in ("autovacuum", "track_counts") and row["setting_value"] == "off":
            findings.append(setting_finding(rule["default_severity"], row))
    return findings


def setting_is(setting_name, unsafe_values):
    """Evaluator: one finding per node whose setting has one of the unsafe values."""
    def evaluate(rows, rule, thresholds):
        return [setting_finding(rule["default_severity"], row) for row in rows
                if row["setting_name"] == setting_name and row["setting_value"] in unsafe_values]
    evaluate.__doc__ = f"{setting_name} in {sorted(unsafe_values)}, per node."
    return evaluate


def evaluate_wal_archiving(evidence, rule, thresholds):
    """PG-BKP-002: on the primary, archiving off (no point-in-time recovery) or on without a command.

    archive_mode on with an empty archive_command and archive_library keeps every WAL file.
    """
    primary = current_primary(evidence["PG_INSTANCE_INVENTORY"])
    if primary is None:
        return []
    settings = settings_by_node(evidence["PG_CONFIGURATION_SNAPSHOT"]).get(primary["target_id"], {})
    mode = settings.get("archive_mode")
    if mode is None:
        return []
    if mode["setting_value"] == "off":
        return [setting_finding("WARNING", mode)]
    command = (settings.get("archive_command") or {}).get("setting_value") or ""
    library = (settings.get("archive_library") or {}).get("setting_value") or ""
    if not command.strip() and not library.strip():
        finding = setting_finding("CRITICAL", settings.get("archive_command") or mode)
        finding["details"]["archive_mode"] = mode["setting_value"]
        finding["template_values"]["value"] = "empty while archive_mode is " + mode["setting_value"]
        finding["template_values"].update({"_alt": True, "archive_mode": mode["setting_value"]})
        return [finding]
    return []


def usable_connections(settings):
    """max_connections minus the slots reserved for superusers and pg_use_reserved_connections."""
    def number(name):
        row = settings.get(name)
        try:
            return int(row["setting_value"]) if row else 0
        except (TypeError, ValueError):
            return 0
    maximum = number("max_connections")
    reserved = number("superuser_reserved_connections") + number("reserved_connections")
    return maximum, reserved, maximum - reserved


def evaluate_connection_capacity(evidence, rule, thresholds):
    """PG-CONN-002: client connections on the primary against its usable connection slots."""
    activity = evidence["PG_CONNECTION_ACTIVITY"]
    nodes = settings_by_node(evidence["PG_CONFIGURATION_SNAPSHOT"])
    primary = current_primary(evidence["PG_INSTANCE_INVENTORY"])
    settings = nodes.get(primary["target_id"]) if primary else None
    if not activity or not settings:
        return []
    maximum, reserved, usable = usable_connections(settings)
    if usable <= 0:
        return []
    row = activity[0]
    connections = row["total_client_connections"] or 0
    percent = round(100 * connections / usable, 1)
    matched_threshold = match_threshold(percent, thresholds, "PERCENT")
    if matched_threshold is None:
        return []
    return [{
        "severity": matched_threshold["severity"],
        "snapshot_id": row["snapshot_id"],
        "template_values": {"connections": connections, "usable": usable, "percent": f"{percent:g}"},
        "observed_value": percent,
        "observed_unit": "PERCENT",
        "subject_type": "SYSTEM",
        "subject_identifier": primary["node_name"],
        "details": {"node": primary["node_name"], "connections": connections,
                    "max_connections": maximum, "reserved_connections": reserved,
                    "usable_connections": usable, "active": row["active_connections"],
                    "idle": row["idle_connections"],
                    "idle_in_transaction": row["idle_in_transaction_connections"],
                    "captured_at": iso(row["captured_at"])},
    }]


def table_name(row):
    return f"{row['database_name']}.{row['schema_name']}.{row['object_name']}"


def table_finding(severity, row, percent, template_values, details):
    return {"severity": severity, "snapshot_id": row["snapshot_id"],
            "template_values": {"table": table_name(row), "percent": f"{percent:g}", **template_values},
            "observed_value": percent, "observed_unit": "PERCENT", "subject_type": "TABLE",
            "subject_identifier": table_name(row),
            "details": {"database": row["database_name"], "table": f"{row['schema_name']}.{row['object_name']}",
                        "live_rows": row["n_live_tup"], **details,
                        "captured_at": iso(row["captured_at"])}}


def ratio_or_size_severity(percent, count, thresholds, large_limit):
    """Ratio thresholds decide; a count beyond the large-table limit is at least a WARNING."""
    matched = match_threshold(percent, thresholds, "PERCENT")
    if matched is not None:
        return matched["severity"], "ratio"
    if count >= large_limit:
        return "WARNING", "large_table"
    return None, None


def evaluate_dead_tuple_pressure(rows, rule, thresholds):
    """PG-MAINT-001: dead rows as a share of all rows, or many dead rows in a large table."""
    minimum = parameter(rule, "min_dead_tuples")
    large = parameter(rule, "large_table_dead_tuples")
    findings = []
    for row in rows:
        dead, live = row["n_dead_tup"] or 0, row["n_live_tup"] or 0
        if dead < minimum:
            continue
        ratio = 100 * dead / (dead + live)     # judged unrounded; shown rounded
        severity, trigger = ratio_or_size_severity(ratio, dead, thresholds, large)
        percent = round(ratio, 1)
        if severity is None:
            continue
        findings.append(table_finding(
            severity, row, percent, {"dead_rows": dead},
            {"dead_rows": dead, "trigger": trigger,
             "last_autovacuum": iso(row["last_autovacuum"]), "last_vacuum": iso(row["last_vacuum"]),
             "autovacuum_count": row["autovacuum_count"]}))
    return findings


def evaluate_stale_statistics(rows, rule, thresholds):
    """PG-MAINT-002: rows changed since the last analyze, as a share of live rows or in a large table."""
    minimum = parameter(rule, "min_modifications")
    large = parameter(rule, "large_table_modifications")
    findings = []
    for row in rows:
        modified, live = row["n_mod_since_analyze"] or 0, row["n_live_tup"] or 0
        if modified < minimum:
            continue
        # An empty table changes nothing for the planner's estimates in percent; judge by count.
        ratio = 100 * modified / live if live else 0.0
        severity, trigger = ratio_or_size_severity(ratio, modified, thresholds, large)
        percent = round(ratio, 1)
        if severity is None:
            continue
        findings.append(table_finding(
            severity, row, percent, {"modified_rows": modified},
            {"modified_rows": modified, "trigger": trigger,
             "never_analyzed": not row["last_analyze"] and not row["last_autoanalyze"],
             "last_autoanalyze": iso(row["last_autoanalyze"]), "last_analyze": iso(row["last_analyze"]),
             "autoanalyze_count": row["autoanalyze_count"]}))
    return findings


def data_mount(data_directory, mounts):
    """The mount holding data_directory: longest mount point that contains it, or None."""
    if not data_directory:
        return None
    best = None
    for m in mounts:
        point = m["mount_point"]
        if data_directory == point or data_directory.startswith(point.rstrip("/") + "/"):
            if best is None or len(point) > len(best["mount_point"]):
                best = m
    return best


def evaluate_data_disk_usage(evidence, rule, thresholds):
    """PG-CAP-001: usage of the filesystem holding data_directory, per node."""
    data_directories = {r["target_id"]: r["setting_value"]
                        for r in evidence["PG_CONFIGURATION_SNAPSHOT"]
                        if r["setting_name"] == "data_directory"}
    findings = []
    for target_id, directory in data_directories.items():
        mounts = [m for m in evidence["PG_HOST_SNAPSHOT"]
                  if m["target_id"] == target_id and m["total_bytes"]]
        mount = data_mount(directory, mounts)
        if mount is None:
            continue
        used_percent = round(usage_percent(mount["used_bytes"], mount["available_bytes"],
                                           mount["total_bytes"]), 1)
        matched_threshold = match_threshold(used_percent, thresholds, "PERCENT")
        if matched_threshold is None:
            continue
        findings.append(
            {
                "severity": matched_threshold["severity"],
                "snapshot_id": mount["snapshot_id"],
                "template_values": {
                    "node_name": mount["node_name"],
                    "mount_point": mount["mount_point"],
                    "used_percent": f"{used_percent:g}",
                    "data_directory": directory,
                },
                "observed_value": used_percent,
                "observed_unit": "PERCENT",
                "subject_type": "NODE",
                "subject_identifier": mount["node_name"],
                "details": {
                    "node": mount["node_name"],
                    "mount_point": mount["mount_point"],
                    "data_directory": directory,
                    "used_bytes": mount["used_bytes"],
                    "total_bytes": mount["total_bytes"],
                    "available_bytes": mount["available_bytes"],
                    "captured_at": iso(mount["captured_at"]),
                },
            }
        )
    return findings


class InsufficientEvidence(Exception):
    """Raised by an evaluator when the evidence it got cannot answer the rule.

    Reason: "SOURCE: [code] English message {values as JSON}"; reports explain the code.
    """

    def __init__(self, source, code, message, **values):
        suffix = f" {json.dumps(values, ensure_ascii=False)}" if values else ""
        super().__init__(f"{source}: [{code}] {message}{suffix}")


class NotApplicable(Exception):
    """Raised by an evaluator when the rule's premise does not exist on this system (no replicas, say).

    Same reason format as InsufficientEvidence; the outcome is NOT_APPLICABLE, not a gap in the data.
    """

    def __init__(self, source, code, message, **values):
        suffix = f" {json.dumps(values, ensure_ascii=False)}" if values else ""
        super().__init__(f"{source}: [{code}] {message}{suffix}")


def no_replicas(status_rows, inventory_rows=()):
    """No replica connected to the primary and none known in recovery: a standalone system."""
    return (not any(r["record_type"] == "REPLICA" for r in status_rows)
            and not any(n["in_recovery"] for n in inventory_rows))


def clock(value):
    """Time in a finding sentence: 'YYYY-MM-DD HH:MM:SS'."""
    return value.strftime("%Y-%m-%d %H:%M:%S") if value is not None else None


def archives(row):
    """Whether the node archives WAL: a primary with archive_mode on/always, a replica only with always."""
    return row["archive_mode"] == "always" or (row["archive_mode"] == "on" and not row["in_recovery"])


def evaluate_archive_failures(rows, rule, thresholds):
    """PG-BKP-001: the last archive failure is newer than the last success (archiving stuck now)."""
    findings = []
    for row in rows:
        failed, archived = row["last_failed_time"], row["last_archived_time"]
        if not archives(row) or failed is None or (archived is not None and archived >= failed):
            continue
        values = {"node_name": row["node_name"], "last_failed_time": clock(failed),
                  "last_failed_wal": row["last_failed_wal"],
                  "last_archived_time": clock(archived) or "never"}
        if archived is None:
            values["_alt"] = True
        findings.append({
            "severity": rule["default_severity"], "snapshot_id": row["snapshot_id"],
            "template_values": values, "observed_value": None, "observed_unit": None,
            "subject_type": "NODE", "subject_identifier": row["node_name"],
            "details": {"node": row["node_name"], "archive_mode": row["archive_mode"],
                        "failed_count": row["failed_count"], "archived_count": row["archived_count"],
                        "last_failed_wal": row["last_failed_wal"],
                        "last_archived_wal": row["last_archived_wal"],
                        "last_failed_time": iso(failed), "last_archived_time": iso(archived),
                        "stats_reset": iso(row["stats_reset"]),
                        "captured_at": iso(row["captured_at"])}})
    return findings


def evaluate_long_prepared_transaction(rows, rule, thresholds):
    """PG-TRAN-005: prepared transactions waiting for COMMIT/ROLLBACK PREPARED, by age."""
    findings = []
    for row in rows:
        if row["record_type"] != "TRANSACTION":
            continue
        age = (row["captured_at"] - row["prepared_at"]).total_seconds()
        matched = match_threshold(age, thresholds, "SECOND")
        if matched is None:
            continue
        findings.append({
            "severity": matched["severity"], "snapshot_id": row["snapshot_id"],
            "template_values": {"gid": row["gid"], "database_name": row["database_name"],
                                "owner": row["owner"], "age_seconds": round(age)},
            "observed_value": round(age, 1), "observed_unit": "SECOND",
            "subject_type": "PREPARED_TRANSACTION", "subject_identifier": row["gid"],
            "details": {"gid": row["gid"], "database": row["database_name"], "user": row["owner"],
                        "transaction_id": row["transaction_id"],
                        "prepared_at": iso(row["prepared_at"]),
                        "captured_at": iso(row["captured_at"])}})
    return findings


def evaluate_recent_failover(rows, rule, thresholds):
    """PG-HA-001: the primary's current timeline began within the recent failover window.

    The history file of the current timeline is written by the primary's own
    promotion; both times come from the same server clock.
    """
    primaries = [r for r in rows if r["in_recovery"] is False and r["timeline_id"] is not None]
    if not primaries:
        raise InsufficientEvidence("PG_WAL_STATUS", "no_primary",
                                   "No primary among the collected nodes.")
    primary = max(primaries, key=lambda r: r["captured_at"])
    if primary["timeline_id"] == 1:
        return []                       # never promoted
    started = primary["timeline_started_at"]
    if started is None:
        raise InsufficientEvidence("PG_WAL_STATUS", "no_timeline_history",
                                   f"History file of timeline {primary['timeline_id']} is not in pg_wal.")
    since = max((primary["captured_at"] - started).total_seconds(), 0.0)
    window = parameter(rule, "recent_failover_window")
    if since > window:
        return []
    return [{
        "severity": rule["default_severity"], "snapshot_id": primary["snapshot_id"],
        "template_values": {"node_name": primary["node_name"], "timeline_id": primary["timeline_id"],
                            "timeline_started_at": clock(started), "since_seconds": round(since)},
        "observed_value": round(since, 1), "observed_unit": "SECOND",
        "subject_type": "NODE", "subject_identifier": primary["node_name"],
        "details": {"node": primary["node_name"], "timeline_id": primary["timeline_id"],
                    "timeline_history_file": primary["timeline_history_file"],
                    "timeline_started_at": iso(started),
                    "captured_at": iso(primary["captured_at"])}}]


# Indexes enforcing a primary key, unique or exclusion constraint are needed without scans.
CONSTRAINT_INDEX_TYPES = {"p", "u", "x"}


def index_name(row):
    return f"{row['database_name']}.{row['schema_name']}.{row['index_name']}"


def evaluate_unused_indexes(rows, rule, thresholds):
    """PG-IDX-001: indexes with no scans summed over all nodes.

    A sum above 0 on the reachable nodes decides "used"; a sum of 0 with a node
    not collected cannot be decided. The statistics age is the shortest over the nodes.
    """
    marker = next((r for r in rows if r["record_type"] == "NODES"), None)
    if marker is None:
        raise InsufficientEvidence("PG_INDEX_USAGE", "no_nodes", "No node list for the target.")
    nodes = {n["target_id"]: n["name"] for n in marker["nodes"]}
    collected = {(r["target_id"], r["database_name"]): r for r in rows if r["record_type"] == "DATABASE"}
    if not collected:
        # Lab 2026-10-29: every node failed to connect; nothing seen is not "nothing unused".
        raise InsufficientEvidence("PG_INDEX_USAGE", "no_index_usage",
                                   "Index usage was not collected from any server.")
    min_size = parameter(rule, "min_index_size")
    min_age = parameter(rule, "min_statistics_age")
    full_cycle = parameter(rule, "full_cycle")

    indexes = {}
    for r in rows:
        if (r["record_type"] != "INDEX" or r["constraint_type"] in CONSTRAINT_INDEX_TYPES
                or r["extension_owned"]):
            continue                                   # extension objects are not the DBA's to drop
        if not r["is_valid"] or r["being_built"]:
            continue                                   # invalid indexes are PG-IDX-002
        entry = indexes.setdefault(index_name(r), {"row": r, "scans": 0, "size": 0})
        entry["scans"] += r["idx_scan"] or 0
        entry["size"] = max(entry["size"], r["index_size_bytes"] or 0)

    findings, undecided, missing_nodes, too_recent = [], [], set(), set()
    for name, entry in indexes.items():
        if entry["scans"] > 0 or entry["size"] < min_size:
            continue
        database = entry["row"]["database_name"]
        missing = [nodes[t] for t in nodes if (t, database) not in collected]
        if missing:
            undecided.append(name)
            missing_nodes.update(missing)
            continue
        stats = [collected[(t, database)] for t in nodes]
        age = min((s["captured_at"] - s["stats_since"]).total_seconds() for s in stats)
        if age < min_age:
            too_recent.add(database)
            continue
        since = min(stats, key=lambda s: s["captured_at"] - s["stats_since"])
        row = entry["row"]
        values = {"index": name, "table": f"{row['schema_name']}.{row['table_name']}",
                  "nodes": ", ".join(nodes.values()), "statistics_seconds": round(age),
                  "index_size": entry["size"]}
        if age < full_cycle:
            values["_alt"] = True
        findings.append({
            "severity": rule["default_severity"], "snapshot_id": row["snapshot_id"],
            "template_values": values, "observed_value": entry["size"], "observed_unit": "BYTE",
            "subject_type": "INDEX", "subject_identifier": name,
            "details": {"database": database, "table": values["table"], "index": name,
                        "index_size_bytes": entry["size"], "nodes_checked": values["nodes"],
                        "statistics_since": iso(since["stats_since"]),
                        "statistics_node": since["node_name"],
                        "statistics_since_start": since["stats_since_start"],
                        "captured_at": iso(row["captured_at"])}})
    if undecided:
        raise InsufficientEvidence(
            "PG_INDEX_USAGE", "index_usage_incomplete",
            f"{len(undecided)} index(es) unused on the reachable nodes; not collected on "
            f"{', '.join(sorted(missing_nodes))}.",
            count=len(undecided), nodes=", ".join(sorted(missing_nodes)))
    if not findings and too_recent:
        raise InsufficientEvidence(
            "PG_INDEX_USAGE", "statistics_too_recent",
            f"Index statistics of {', '.join(sorted(too_recent))} are younger than {round(min_age / 86400)} days.",
            databases=", ".join(sorted(too_recent)), minimum_days=round(min_age / 86400))
    return sorted(findings, key=lambda f: -f["observed_value"])


def evaluate_invalid_indexes(rows, rule, thresholds):
    """PG-IDX-002: invalid indexes on the primary; a unique one does not enforce uniqueness.

    Read from the primary only: an index still being built shows as invalid on replicas too.
    """
    primaries = [r for r in rows if r["record_type"] == "DATABASE" and r["in_recovery"] is False]
    if not primaries:
        raise InsufficientEvidence("PG_INDEX_USAGE", "no_primary", "No primary among the collected nodes.")
    primary = max(primaries, key=lambda r: r["captured_at"])["target_id"]
    findings = []
    for r in rows:
        if (r["record_type"] != "INDEX" or r["target_id"] != primary or r["is_valid"]
                or r["being_built"] or r["extension_owned"]):
            continue
        name = index_name(r)
        values = {"index": name, "table": f"{r['schema_name']}.{r['table_name']}"}
        if r["is_unique"]:
            values["_alt"] = True
        findings.append({
            "severity": "CRITICAL" if r["is_unique"] else rule["default_severity"],
            "snapshot_id": r["snapshot_id"], "template_values": values,
            "observed_value": None, "observed_unit": None,
            "subject_type": "INDEX", "subject_identifier": name,
            "details": {"database": r["database_name"], "table": values["table"], "index": name,
                        "unique": r["is_unique"], "index_size_bytes": r["index_size_bytes"],
                        "node": r["node_name"], "captured_at": iso(r["captured_at"])}})
    return findings


def evaluate_public_create(rows, rule, thresholds):
    """PG-SEC-004: user schemas where PUBLIC has CREATE."""
    return [{
        "severity": rule["default_severity"], "snapshot_id": r["snapshot_id"],
        "template_values": {"database": r["database_name"], "schema": r["schema_name"]},
        "observed_value": None, "observed_unit": None,
        "subject_type": "SCHEMA", "subject_identifier": f"{r['database_name']}.{r['schema_name']}",
        "details": {"database": r["database_name"], "schema": r["schema_name"],
                    "schema_owner": r["schema_owner"], "captured_at": iso(r["captured_at"])}}
        for r in rows if r["record_type"] == "SCHEMA" and r["public_create"]]


# The bootstrap superuser created by initdb always has OID 10.
BOOTSTRAP_SUPERUSER_OID = 10


def evaluate_login_superusers(rows, rule, thresholds):
    """PG-SEC-001: login superusers other than the bootstrap superuser."""
    return [{
        "severity": rule["default_severity"], "snapshot_id": r["snapshot_id"],
        "template_values": {"role": r["role_name"]},
        "observed_value": None, "observed_unit": None,
        "subject_type": "ROLE", "subject_identifier": r["role_name"],
        "details": {"role": r["role_name"], "valid_until": iso(r["valid_until"]),
                    "captured_at": iso(r["captured_at"])}}
        for r in rows if r["is_superuser"] and r["can_login"]
        and int(r["role_oid"]) != BOOTSTRAP_SUPERUSER_OID]


# Largest value per integer column type; other types are limited by the sequence only.
COLUMN_TYPE_LIMITS = {"smallint": (-32768, 32767), "integer": (-2147483648, 2147483647),
                      "bigint": (-9223372036854775808, 9223372036854775807)}


def sequence_limit(row):
    """(limit, source): the bound the sequence moves towards; the column type wins when it is tighter."""
    ascending = (row["increment_by"] or 1) > 0
    limit, source = (row["max_value"], "sequence") if ascending else (row["min_value"], "sequence")
    column = COLUMN_TYPE_LIMITS.get(row["column_type"] or "")
    if column:
        bound = column[1] if ascending else column[0]
        if abs(bound) < abs(limit):
            limit, source = bound, "column"
    return int(limit), source


def evaluate_sequence_exhaustion(rows, rule, thresholds):
    """PG-CAP-002: used share of a sequence's limit (its own type or the column it feeds).

    Unreadable sequences (no SELECT/USAGE) are never treated as healthy.
    """
    findings, unreadable = [], []
    for r in rows:
        if r["record_type"] != "SEQUENCE" or r["is_cycle"]:
            continue                                   # cycling sequences wrap on purpose
        name = f"{r['database_name']}.{r['schema_name']}.{r['sequence_name']}"
        if not r["is_readable"]:
            unreadable.append(name)
            continue
        if r["last_value"] is None:
            continue                                   # never used
        limit, source = sequence_limit(r)
        last = int(r["last_value"])
        ratio = 100 * last / limit if limit else 0.0  # judged unrounded; shown rounded
        matched = match_threshold(ratio, thresholds, "PERCENT")
        if matched is None:
            continue
        percent = round(ratio, 1)
        column = f"{r['schema_name']}.{r['table_name']}.{r['column_name']}" if r["table_name"] else "-"
        findings.append({
            "severity": matched["severity"], "snapshot_id": r["snapshot_id"],
            "template_values": {"sequence": name, "column": column, "percent": f"{percent:g}",
                                "last_value": last, "limit": limit},
            "observed_value": percent, "observed_unit": "PERCENT",
            "subject_type": "SEQUENCE", "subject_identifier": name,
            "details": {"database": r["database_name"], "sequence": name, "column": column,
                        "data_type": r["data_type"], "column_type": r["column_type"],
                        "last_value": last, "limit": limit, "limit_source": source,
                        "captured_at": iso(r["captured_at"])}})
    if unreadable and not findings:
        # Named, so the DBA knows where to grant (the grant is per database and schema).
        names = ", ".join(unreadable[:5]) + (f" (+{len(unreadable) - 5})" if len(unreadable) > 5 else "")
        raise InsufficientEvidence(
            "PG_SEQUENCE_CAPACITY", "sequence_privilege_missing",
            f"{len(unreadable)} sequence(s) could not be read; the collecting role needs SELECT on them.",
            count=len(unreadable), names=names)
    return findings


# -----------------------------------------------------------------------------
# Evaluation Registry
# -----------------------------------------------------------------------------
# Evidence loaders translate Dictionary evidence_source keys into repository
# queries. Keeping this mapping here lets run_assessment() load only the evidence
# declared by each rule without knowing PostgreSQL table/query details.
EVIDENCE_LOADERS = {
    "PG_ACTIVITY_SNAPSHOT": load_latest_activity_snapshot,
    "PG_TRANSACTION_WRAPAROUND": load_latest_transaction_wraparound_snapshot,
    "PG_REPLICATION_SLOTS": load_latest_replication_slot_snapshot,
    "PG_CONNECTION_ACTIVITY": load_latest_connection_activity_snapshot,
    "PG_HOST_SNAPSHOT": load_latest_storage_snapshot,
    "PG_CONFIGURATION_SNAPSHOT": load_latest_configuration_snapshot,
    "PG_REPLICATION_STATUS": load_latest_replication_status,
    "PG_INSTANCE_INVENTORY": load_instance_inventory,
    "PG_VACUUM_ANALYZE": load_latest_vacuum_analyze_snapshot,
    "PG_WAL_STATUS": load_latest_wal_status,
    "PG_PREPARED_TRANSACTIONS": load_latest_prepared_transactions,
    "PG_INDEX_USAGE": load_latest_index_usage,
    "PG_SCHEMA_PRIVILEGES": load_latest_schema_privileges,
    "PG_ROLES": load_latest_roles,
    "PG_SEQUENCE_CAPACITY": load_latest_sequence_capacity,
}

# Evaluators contain the rule-specific PostgreSQL engineering logic. All
# evaluators use the same (rows, rule, thresholds) contract so run_assessment()
# can dispatch rules generically instead of growing a rule-specific if/elif tree.
# Rules with one evidence source get its rows; rules with several get
# {evidence_source: rows}.
RULE_EVALUATORS = {
    "PG-TRAN-001": evaluate_long_idle_transaction,
    "PG-TRAN-002": evaluate_database_xid_wraparound,
    "PG-TRAN-003": evaluate_long_running_transaction,
    "PG-REP-001": evaluate_replication_slot_wal_retention_pressure,
    "PG-REP-002": evaluate_replication_slot_wal_unavailable,
    "PG-CONN-001": evaluate_aborted_idle_transaction_connections,
    "PG-CAP-001": evaluate_data_disk_usage,
    "PG-REP-003": evaluate_replication_lag,
    "PG-REP-004": evaluate_replica_not_streaming,
    "PG-REP-005": evaluate_inactive_replication_slot,
    "PG-REP-006": evaluate_sync_standby_missing,
    "PG-CONF-001": evaluate_pending_restart,
    "PG-CONF-002": evaluate_unsafe_durability,
    "PG-CONF-004": evaluate_autovacuum_disabled,
    "PG-CONN-002": evaluate_connection_capacity,
    "PG-TRAN-004": evaluate_database_mxid_wraparound,
    "PG-BKP-002": evaluate_wal_archiving,
    "PG-SEC-002": setting_is("password_encryption", {"md5"}),
    "PG-SEC-003": setting_is("ssl", {"off"}),
    "PG-MAINT-001": evaluate_dead_tuple_pressure,
    "PG-MAINT-002": evaluate_stale_statistics,
    "PG-BKP-001": evaluate_archive_failures,
    "PG-TRAN-005": evaluate_long_prepared_transaction,
    "PG-HA-001": evaluate_recent_failover,
    "PG-IDX-001": evaluate_unused_indexes,
    "PG-IDX-002": evaluate_invalid_indexes,
    "PG-SEC-001": evaluate_login_superusers,
    "PG-SEC-004": evaluate_public_create,
    "PG-CAP-002": evaluate_sequence_exhaustion,
}


# -----------------------------------------------------------------------------
# Freshness Validation
# -----------------------------------------------------------------------------

def validate_evidence_freshness(
    rows,
    requirement,
    evaluation_time,
):
    """(valid, reason): newest row must be within max_age_seconds of evaluation_time."""
    if not rows:
        if requirement["is_required"]:
            return False, "Required evidence is not available."

        return True, None

    latest_captured_at = max(
        row["captured_at"]
        for row in rows
    )

    max_age_seconds = requirement["max_age_seconds"]

    if max_age_seconds is None:
        return True, None

    evidence_age_seconds = (
        evaluation_time - latest_captured_at
    ).total_seconds()

    if evidence_age_seconds > max_age_seconds:
        return (
            False,
            (
                f"Evidence is stale. "
                f"Age={evidence_age_seconds:.1f}s, "
                f"MaxAge={max_age_seconds}s"
            ),
        )

    return True, None

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
# Assessment result outcomes (ADR-0014). assessment_run.status stays technical.
OUTCOME_HEALTHY = "HEALTHY"
OUTCOME_ATTENTION_REQUIRED = "ATTENTION_REQUIRED"
OUTCOME_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
OUTCOME_ERROR = "ERROR"
OUTCOME_NOT_APPLICABLE = "NOT_APPLICABLE"     # the rule's premise does not exist here (ADR-0014)


def highest_severity(findings):
    """Return the most severe finding severity, or None for no findings."""
    if not findings:
        return None

    return max(
        (finding["severity"] for finding in findings),
        key=lambda severity: SEVERITY_RANK.get(severity, 0),
    )


# Capture times come from the targets' clocks, check times from the repository's.
CLOCK_SKEW_TOLERANCE_SECONDS = 120


def current_rows(rows, requirement, evaluation_time, source=None, uncollected=None):
    """Rows that describe the present, each judged on its own capture time.

    A node whose collection failed keeps its last snapshot in the repository;
    that snapshot must not be judged as the node's current state. uncollected
    is {(target_id, evidence_source)} a health check failed to collect.
    """
    max_age = requirement["max_age_seconds"]
    return [r for r in rows
            if (max_age is None or (evaluation_time - r["captured_at"]).total_seconds() <= max_age)
            and (r.get("target_id"), source) not in (uncollected or ())]


def evaluate_rule(conn, rule, target_id, evaluation_time, evidence_cache, uncollected=None):
    """Evaluate one rule -> (outcome, findings, reason).

    Missing/stale evidence returns INSUFFICIENT_EVIDENCE; real problems raise.
    """
    evaluator = RULE_EVALUATORS.get(rule["rule_key"])
    if evaluator is None:
        raise RuntimeError(
            f"No evaluator registered for rule: {rule['rule_key']}"
        )

    thresholds = load_thresholds(conn, rule["rule_id"])
    rule = {**rule, "parameters": load_parameters(conn, rule["rule_id"])}
    evidence_requirements = load_evidence_requirements(
        conn,
        rule["rule_id"],
    )

    if not evidence_requirements:
        raise RuntimeError(
            f"No evidence requirements defined for rule: {rule['rule_key']}"
        )

    logger.debug("Evidence requirements:")
    for requirement in evidence_requirements:
        logger.debug("%s", requirement)

    # Loading and freshness checks stay generic: every declared source must be fresh.
    evidence_sets = {}

    for requirement in evidence_requirements:
        evidence_source = requirement["evidence_source"]
        loader = EVIDENCE_LOADERS.get(evidence_source)

        if loader is None:
            raise RuntimeError(
                f"No evidence loader registered for source: {evidence_source}"
            )

        # Evidence is read-only; rows stay valid for later rules even if the
        # rule that loaded them is rolled back.
        if evidence_source not in evidence_cache:
            evidence_cache[evidence_source] = loader(conn, target_id)

        loaded = evidence_cache[evidence_source]
        rows = current_rows(loaded, requirement, evaluation_time, evidence_source, uncollected)
        valid, reason = validate_evidence_freshness(
            rows or loaded,
            requirement,
            evaluation_time,
        )
        if valid and not rows and loaded:
            # Only rows of targets this health check could not collect.
            valid, reason = validate_evidence_freshness([], requirement, evaluation_time)

        if not valid:
            if not requirement["is_required"]:
                # Optional evidence that is stale is treated as absent, never as current.
                evidence_sets[evidence_source] = []
                continue
            return (
                OUTCOME_INSUFFICIENT_EVIDENCE,
                [],
                f"{evidence_source}: {reason}",
            )

        evidence_sets[evidence_source] = rows

    evidence = (next(iter(evidence_sets.values()))
                if len(evidence_sets) == 1 else evidence_sets)
    try:
        findings = evaluator(evidence, rule, thresholds)
    except InsufficientEvidence as exc:
        return OUTCOME_INSUFFICIENT_EVIDENCE, [], str(exc)
    except NotApplicable as exc:
        return OUTCOME_NOT_APPLICABLE, [], str(exc)

    if findings:
        return OUTCOME_ATTENTION_REQUIRED, findings, None

    return OUTCOME_HEALTHY, [], None


def mark_run_failed(conn, assessment_run_id, exc):
    """Mark the run FAILED; falls back to a fresh connection if needed."""
    message = f"{type(exc).__name__}: {exc}"

    try:
        conn.rollback()
        complete_assessment_run(conn, assessment_run_id, "FAILED", message)
        conn.commit()
        return
    except Exception:
        pass

    try:
        with connect_repository() as fresh_conn:
            complete_assessment_run(
                fresh_conn,
                assessment_run_id,
                "FAILED",
                message,
            )
    except Exception as mark_exc:
        logger.critical(
            "Could not mark assessment run %s as FAILED: %s",
            assessment_run_id,
            mark_exc,
            extra={"context": {"assessment_run_id": assessment_run_id}},
        )


def run_assessment(
    conn,
    assessment_key,
    target_id,
    evaluation_time=None,
    scheduled_at=None,
    health_check_id=None,
    uncollected=None,
):
    """Run all enabled rules of one assessment for one target; returns run id.

    One transaction per rule: a failing rule becomes ERROR, others continue
    (run PARTIAL). evaluation_time defaults to now; scheduled_at is set by
    the agent for scheduled runs. Details: ADR-0014, ADR-0015.
    """
    if evaluation_time is None:
        evaluation_time = datetime.now(timezone.utc)

    assessment = load_assessment(conn, assessment_key)
    logger.debug("Assessment:")
    logger.debug("%s", assessment)

    assessment_run_id = create_assessment_run(
        conn,
        assessment["assessment_id"],
        target_id,
        datetime.now(timezone.utc),
        scheduled_at,
        health_check_id,
    )
    conn.commit()
    logger.debug("Assessment Run ID: %s", assessment_run_id)

    try:
        rules = load_rules(conn, assessment["assessment_id"])
        conn.commit()

        # One evidence load per source per run, shared by all rules.
        evidence_cache = {}
        error_count = 0
        outcome_counts = {}

        for rule in rules:
            logger.debug("")
            logger.debug("Evaluating %s - %s", rule["rule_key"], rule["name"])

            try:
                with conn.transaction():
                    outcome, findings, reason = evaluate_rule(
                        conn,
                        rule,
                        target_id,
                        evaluation_time,
                        evidence_cache,
                        uncollected,
                    )

                    for finding in findings:
                        finding_id = insert_finding(
                            conn,
                            assessment_run_id,
                            rule,
                            finding,
                        )
                        logger.debug(
                            "Finding %s: %s - %s",
                            finding_id,
                            finding["severity"],
                            rule["name"],
                        )

                    insert_assessment_result(
                        conn,
                        assessment_run_id,
                        rule,
                        outcome,
                        highest_severity(findings),
                        len(findings),
                        reason,
                        evaluation_time,
                        load_thresholds(conn, rule["rule_id"]),
                        load_parameters(conn, rule["rule_id"]),
                    )

            except Exception as exc:
                # Rule's work (incl. findings) was rolled back; record ERROR.
                error_count += 1
                outcome = OUTCOME_ERROR
                reason = f"{type(exc).__name__}: {exc}"

                # Full traceback to log/event_log; result keeps the message.
                logger.warning(
                    "Rule %s ended with ERROR in assessment run %s: %s",
                    rule["rule_key"],
                    assessment_run_id,
                    reason,
                    exc_info=True,
                    extra={
                        "context": {
                            "assessment_run_id": assessment_run_id,
                            "rule_key": rule["rule_key"],
                        }
                    },
                )

                with conn.transaction():
                    insert_assessment_result(
                        conn,
                        assessment_run_id,
                        rule,
                        outcome,
                        None,
                        0,
                        reason,
                        evaluation_time,
                    )

            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            logger.debug(
                "Outcome: %s%s",
                outcome,
                f" ({reason})" if reason else "",
            )

        status = "PARTIAL" if error_count else "SUCCESS"
        status_message = (
            f"{error_count} rule(s) ended with ERROR." if error_count else None
        )

        complete_assessment_run(
            conn,
            assessment_run_id,
            status,
            status_message,
        )
        conn.commit()

    except Exception as exc:
        mark_run_failed(conn, assessment_run_id, exc)
        logger.error(
            "Assessment run %s FAILED: %s",
            assessment_run_id,
            exc,
            exc_info=True,
            extra={"context": {"assessment_run_id": assessment_run_id}},
        )
        raise

    # One line per run: parallel runs in the agent cannot interleave it.
    logger.info(
        "Assessment run %s %s on target %s -> %s: %s",
        assessment_run_id,
        assessment_key,
        target_id,
        status,
        ", ".join(f"{count} {name}" for name, count in sorted(outcome_counts.items()))
        or "no rules",
    )

    return assessment_run_id


# Development defaults. They keep `python -m repository.intelligence.assessment_engine`
# without arguments behaving exactly as before the CLI was introduced.
DEFAULT_ASSESSMENT_KEY = "PG_CONNECTION_HEALTH"
DEFAULT_TARGET_ID = 1


def parse_args(argv=None):
    """Select assessment and target only; rule behaviour is not a CLI option."""
    parser = argparse.ArgumentParser(
        prog="python -m repository.intelligence.assessment_engine",
        description="Run one Keystone assessment against one target.",
    )
    parser.add_argument(
        "--assessment",
        default=DEFAULT_ASSESSMENT_KEY,
        help=(
            "assessment_key from keystone.assessment_definition "
            f"(default: {DEFAULT_ASSESSMENT_KEY})"
        ),
    )
    parser.add_argument(
        "--target",
        type=int,
        default=DEFAULT_TARGET_ID,
        help=f"target_id from keystone.target (default: {DEFAULT_TARGET_ID})",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    configure_logging("assessment_engine", connect=connect_repository)
    # A manual run shows rule-by-rule detail; the agent logs one line per run.
    logger.setLevel(logging.DEBUG)

    with connect_repository() as conn:
        run_assessment(
            conn,
            args.assessment,
            args.target,
        )


if __name__ == "__main__":
    main()
