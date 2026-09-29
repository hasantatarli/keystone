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
def main():
    target_id = 1
    evaluation_time = datetime.now(timezone.utc)

    with connect_repository() as conn:
        assessment = load_assessment(
            conn,
            "PG_TRANSACTION_HEALTH",
        )

        print("Assessment:")
        print(assessment)

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
                        print(finding)

if __name__ == "__main__":
    main()