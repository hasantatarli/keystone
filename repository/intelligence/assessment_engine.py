# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------
import argparse
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
):
    """Persist the outcome of one rule in one run (ADR-0014), with the thresholds used."""
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
                thresholds_used
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
            ),
        )


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
                details
            )
            VALUES
            (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
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
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                snapshot_id,
                target_id,
                captured_at,
                slot_name,
                plugin,
                slot_type,
                database_name,
                temporary,
                active,
                active_pid,
                slot_xmin,
                catalog_xmin,
                restart_lsn,
                confirmed_flush_lsn,
                wal_status,
                safe_wal_size,
                two_phase,
                conflicting,
                invalidation_reason,
                failover
            FROM postgresql.replication_slot_snapshot
            WHERE target_id = %s
              AND captured_at =
              (
                  SELECT MAX(captured_at)
                  FROM postgresql.replication_slot_snapshot
                  WHERE target_id = %s
              )
            ORDER BY slot_name
            """,
            (target_id, target_id),
        )

        return cur.fetchall()


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


def evaluate_replication_slot_wal_retention_pressure(
    rows,
    rule,
    thresholds,
):
    """PG-REP-001: slots with wal_status extended; severity from the rule."""
    findings = []

    for row in rows:
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

    for row in rows:
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
}

# Evaluators contain the rule-specific PostgreSQL engineering logic. All
# evaluators use the same (rows, rule, thresholds) contract so run_assessment()
# can dispatch rules generically instead of growing a rule-specific if/elif tree.
RULE_EVALUATORS = {
    "PG-TRAN-001": evaluate_long_idle_transaction,
    "PG-TRAN-002": evaluate_database_xid_wraparound,
    "PG-TRAN-003": evaluate_long_running_transaction,
    "PG-REP-001": evaluate_replication_slot_wal_retention_pressure,
    "PG-REP-002": evaluate_replication_slot_wal_unavailable,
    "PG-CONN-001": evaluate_aborted_idle_transaction_connections,
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


def highest_severity(findings):
    """Return the most severe finding severity, or None for no findings."""
    if not findings:
        return None

    return max(
        (finding["severity"] for finding in findings),
        key=lambda severity: SEVERITY_RANK.get(severity, 0),
    )


def evaluate_rule(conn, rule, target_id, evaluation_time, evidence_cache):
    """Evaluate one rule -> (outcome, findings, reason).

    Missing/stale evidence returns INSUFFICIENT_EVIDENCE; real problems raise.
    """
    evaluator = RULE_EVALUATORS.get(rule["rule_key"])
    if evaluator is None:
        raise RuntimeError(
            f"No evaluator registered for rule: {rule['rule_key']}"
        )

    thresholds = load_thresholds(conn, rule["rule_id"])
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

    # MVP evaluators currently consume one evidence row-set. Keep evidence
    # loading and freshness checks generic so new rules do not add branches
    # to the orchestration loop. Expand the evaluator input contract only
    # when a real multi-source rule requires it.
    evidence_sets = []

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

        rows = evidence_cache[evidence_source]
        valid, reason = validate_evidence_freshness(
            rows,
            requirement,
            evaluation_time,
        )

        if not valid:
            return (
                OUTCOME_INSUFFICIENT_EVIDENCE,
                [],
                f"{evidence_source}: {reason}",
            )

        evidence_sets.append(rows)

    if len(evidence_sets) != 1:
        raise RuntimeError(
            f"Rule {rule['rule_key']} has {len(evidence_sets)} evidence "
            "sources; MVP evaluators currently support exactly one."
        )

    findings = evaluator(
        evidence_sets[0],
        rule,
        thresholds,
    )

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
