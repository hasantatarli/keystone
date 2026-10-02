# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------
import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


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
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO keystone.assessment_run
            (
                assessment_id,
                target_id,
                started_at,
                status
            )
            VALUES
            (
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
            ),
        )

        return cur.fetchone()["assessment_run_id"]


def complete_assessment_run(
    conn,
    assessment_run_id,
    status,
):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE keystone.assessment_run
            SET
                finished_at = clock_timestamp(),
                status = %s
            WHERE assessment_run_id = %s
            """,
            (
                status,
                assessment_run_id,
            ),
        )

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
                subject_identifier
            )
            VALUES
            (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
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

# -----------------------------------------------------------------------------
# Rule Evaluation
# -----------------------------------------------------------------------------
def evaluate_long_idle_transaction(rows, thresholds):
    findings = []

    for row in rows:
        if row["backend_type"] != "client backend":
            continue

        if row["state"] != "idle in transaction":
            continue

        if row["transaction_start"] is None:
            continue

        duration_seconds = (
            row["captured_at"] - row["transaction_start"]
        ).total_seconds()

        matched_threshold = None

        for threshold in thresholds:
            if threshold["threshold_unit"] != "SECOND":
                continue

            if duration_seconds >= float(threshold["threshold_value"]):
                matched_threshold = threshold
                break

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
            }
        )

    return findings


def evaluate_database_xid_wraparound(rows, thresholds):
    findings = []

    for row in rows:
        xid_age = row["xid_age"]

        matched_threshold = None

        for threshold in thresholds:
            if threshold["threshold_unit"] != "TRANSACTION":
                continue

            if xid_age >= float(threshold["threshold_value"]):
                matched_threshold = threshold
                break

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
    default_severity,
):
    findings = []

    for row in rows:
        if row["wal_status"] != "extended":
            continue

        findings.append(
            {
                "slot_name": row["slot_name"],
                "wal_status": row["wal_status"],
                "severity": default_severity,
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
    default_severity,
):
    findings = []

    for row in rows:
        if row["wal_status"] not in ("unreserved", "lost"):
            continue

        findings.append(
            {
                "slot_name": row["slot_name"],
                "wal_status": row["wal_status"],
                "severity": default_severity,
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

# -----------------------------------------------------------------------------
# Freshness Validation
# -----------------------------------------------------------------------------

def validate_evidence_freshness(
    rows,
    requirement,
    evaluation_time,
):
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
def run_assessment(
    conn,
    assessment_key,
    target_id,
):
    evaluation_time = datetime.now(timezone.utc)

    assessment = load_assessment(
        conn,
        assessment_key,
    )

    print("Assessment:")
    print(assessment)

    assessment_run_id = create_assessment_run(
        conn,
        assessment["assessment_id"],
        target_id,
        evaluation_time,
    )

    print(f"Assessment Run ID: {assessment_run_id}")

    rules = load_rules(
        conn,
        assessment["assessment_id"],
    )

    activity_rows = load_latest_activity_snapshot(
        conn,
        target_id,
    )

    print()
    print(
        f"Latest activity snapshot contains "
        f"{len(activity_rows)} row(s)."
    )

    wraparound_rows = load_latest_transaction_wraparound_snapshot(
        conn,
        target_id,
    )

    print(
        f"Latest transaction wraparound snapshot contains "
        f"{len(wraparound_rows)} row(s)."
    )

    replication_slot_rows = load_latest_replication_slot_snapshot(
        conn,
        target_id,
    )

    print(
        f"Latest replication slot snapshot contains "
        f"{len(replication_slot_rows)} row(s)."
    )

    for rule in rules:
        print()
        print(f"Evaluating {rule['rule_key']} - {rule['name']}")

        thresholds = load_thresholds(
            conn,
            rule["rule_id"],
        )

        evidence_requirements = load_evidence_requirements(
            conn,
            rule["rule_id"],
        )

        print("Evidence requirements:")
        for requirement in evidence_requirements:
            print(requirement)

        if rule["rule_key"] == "PG-TRAN-001":
            requirement = next(
                (
                    item
                    for item in evidence_requirements
                    if item["evidence_source"] == "PG_ACTIVITY_SNAPSHOT"
                ),
                None,
            )

            if requirement is None:
                raise RuntimeError(
                    "PG-TRAN-001 requires PG_ACTIVITY_SNAPSHOT "
                    "but no evidence requirement is defined."
                )

            evidence_valid, reason = validate_evidence_freshness(
                activity_rows,
                requirement,
                evaluation_time,
            )

            if not evidence_valid:
                print(f"Evaluation skipped: {reason}")
                continue

            findings = evaluate_long_idle_transaction(
                activity_rows,
                thresholds,
            )

            if not findings:
                print("No findings.")

            for finding in findings:
                finding_id = insert_finding(
                    conn,
                    assessment_run_id,
                    rule,
                    finding,
                )

                print(
                    f"Finding {finding_id}: "
                    f"{finding['severity']} - "
                    f"PID {finding['pid']} - "
                    f"{finding['duration_seconds']:.1f}s"
                )

        elif rule["rule_key"] == "PG-TRAN-002":
            requirement = next(
                (
                    item
                    for item in evidence_requirements
                    if item["evidence_source"]
                    == "PG_TRANSACTION_WRAPAROUND"
                ),
                None,
            )

            if requirement is None:
                raise RuntimeError(
                    "PG-TRAN-002 requires PG_TRANSACTION_WRAPAROUND "
                    "but no evidence requirement is defined."
                )

            evidence_valid, reason = validate_evidence_freshness(
                wraparound_rows,
                requirement,
                evaluation_time,
            )

            if not evidence_valid:
                print(f"Evaluation skipped: {reason}")
                continue

            findings = evaluate_database_xid_wraparound(
                wraparound_rows,
                thresholds,
            )

            if not findings:
                print("No findings.")

            for finding in findings:
                finding_id = insert_finding(
                    conn,
                    assessment_run_id,
                    rule,
                    finding,
                )

                print(
                    f"Finding {finding_id}: "
                    f"{finding['severity']} - "
                    f"Database {finding['database_name']} - "
                    f"XID age {finding['xid_age']}"
                )
        elif rule["rule_key"] == "PG-REP-001":
            requirement = next(
                (
                    item
                    for item in evidence_requirements
                    if item["evidence_source"] == "PG_REPLICATION_SLOTS"
                ),
                None,
            )

            if requirement is None:
                raise RuntimeError(
                    "PG-REP-001 requires PG_REPLICATION_SLOTS "
                    "but no evidence requirement is defined."
                )

            evidence_valid, reason = validate_evidence_freshness(
                replication_slot_rows,
                requirement,
                evaluation_time,
            )

            if not evidence_valid:
                print(f"Evaluation skipped: {reason}")
                continue

            findings = evaluate_replication_slot_wal_retention_pressure(
                replication_slot_rows,
                rule["default_severity"],
            )

            if not findings:
                print("No findings.")

            for finding in findings:
                finding_id = insert_finding(
                    conn,
                    assessment_run_id,
                    rule,
                    finding,
                )

                print(
                    f"Finding {finding_id}: "
                    f"{finding['severity']} - "
                    f"Slot {finding['slot_name']} - "
                    f"WAL status {finding['wal_status']}"
                )

        elif rule["rule_key"] == "PG-REP-002":
            requirement = next(
                (
                    item
                    for item in evidence_requirements
                    if item["evidence_source"] == "PG_REPLICATION_SLOTS"
                ),
                None,
            )

            if requirement is None:
                raise RuntimeError(
                    "PG-REP-002 requires PG_REPLICATION_SLOTS "
                    "but no evidence requirement is defined."
                )

            evidence_valid, reason = validate_evidence_freshness(
                replication_slot_rows,
                requirement,
                evaluation_time,
            )

            if not evidence_valid:
                print(f"Evaluation skipped: {reason}")
                continue

            findings = evaluate_replication_slot_wal_unavailable(
                replication_slot_rows,
                rule["default_severity"],
            )

            if not findings:
                print("No findings.")

            for finding in findings:
                finding_id = insert_finding(
                    conn,
                    assessment_run_id,
                    rule,
                    finding,
                )

                print(
                    f"Finding {finding_id}: "
                    f"{finding['severity']} - "
                    f"Slot {finding['slot_name']} - "
                    f"WAL status {finding['wal_status']}"
                )
    complete_assessment_run(
        conn,
        assessment_run_id,
        "SUCCESS",
    )

    print(
        f"Assessment Run {assessment_run_id} "
        f"completed successfully."
    )


def main():
    target_id = 1

    with connect_repository() as conn:
        run_assessment(
            conn,
            "PG_REPLICATION_HEALTH",
            target_id,
        )


if __name__ == "__main__":
    main()