"""One-command health check: collect what the assessments need, then assess (MVP Plan Phase 1).

A SYSTEM target includes its NODE targets (ADR-0009). Collection uses the
normal queue, worker and run history (ADR-0015); this command runs its own
worker pool, so no agent is needed. A failed collector does not stop the
health check; its rules end INSUFFICIENT_EVIDENCE and the reason is kept.

    python -m repository.healthcheck.health_check --target 1
"""

import argparse
import getpass
import time
import uuid

from repository.agent.pool import WorkerPool
from repository.common.logging_config import configure_logging, get_logger
from repository.intelligence import assessment_engine
from repository.worker import worker


logger = get_logger("health_check")

# Collectors that describe the target in the report; not required by a rule.
# Optional ones run only where they are already assigned (e.g. SSH host access).
REPORT_CONTEXT_COLLECTORS = {
    "PostgreSQL": {
        "required": ["PG_DATABASE_INVENTORY", "PG_INSTANCE_INVENTORY", "PG_CONFIGURATION_SNAPSHOT"],
        "optional": ["PG_HOST_SNAPSHOT"],
    },
}

DEFAULT_WAIT_MINUTES = 10          # per collector, from its start
POLL_SECONDS = 1


# -----------------------------------------------------------------------------
# Planning: which collector runs on which target
# -----------------------------------------------------------------------------

def load_target_tree(conn, target_id):
    """The target and, for a SYSTEM target, its active NODE children."""
    target = conn.execute(
        "SELECT target_id, name, provider, target_type, is_active "
        "FROM keystone.target WHERE target_id = %s", (target_id,)
    ).fetchone()
    if target is None:
        raise ValueError(f"Target {target_id} does not exist.")
    if not target["is_active"]:
        raise ValueError(f"Target {target_id} is not active.")

    nodes = conn.execute(
        "SELECT target_id, name, provider, target_type FROM keystone.target "
        "WHERE parent_target_id = %s AND target_type = 'NODE' AND is_active "
        "ORDER BY target_id", (target_id,)
    ).fetchall()
    return target, nodes


def load_assessments(conn, provider, assessment_key=None):
    rows = conn.execute(
        "SELECT assessment_key FROM keystone.assessment_definition "
        "WHERE provider = %s AND is_enabled "
        "AND (%s::text IS NULL OR assessment_key = %s) ORDER BY assessment_key",
        (provider, assessment_key, assessment_key),
    ).fetchall()
    keys = [r["assessment_key"] for r in rows]
    if assessment_key and not keys:
        raise ValueError(f"Assessment {assessment_key} not found or disabled for {provider}.")
    return keys


def load_evidence_collectors(conn, assessment_keys):
    """Collector keys required by enabled rules of the given assessments."""
    rows = conn.execute(
        """
        SELECT DISTINCT rer.evidence_source
        FROM keystone.rule_evidence_requirement rer
        JOIN keystone.rule_definition rd ON rd.rule_id = rer.rule_id
        JOIN keystone.assessment_definition ad ON ad.assessment_id = rd.assessment_id
        WHERE ad.assessment_key = ANY(%s) AND rd.is_enabled AND rer.is_required
        ORDER BY rer.evidence_source
        """,
        (assessment_keys,),
    ).fetchall()
    return [r["evidence_source"] for r in rows]


def load_collectors(conn, keys):
    rows = conn.execute(
        "SELECT collector_id, collector_key, execution_scope, execution_type "
        "FROM keystone.collector_definition WHERE collector_key = ANY(%s) AND is_active",
        (list(keys),),
    ).fetchall()
    return {r["collector_key"]: r for r in rows}


def plan_collections(conn, target, nodes, assessment_keys):
    """[(target, collector_key, purpose, optional)] — NODE-scope collectors go to every node."""
    evidence = load_evidence_collectors(conn, assessment_keys)
    context = REPORT_CONTEXT_COLLECTORS.get(target["provider"], {})
    wanted = ([(k, "EVIDENCE", False) for k in evidence]
              + [(k, "CONTEXT", False) for k in context.get("required", []) if k not in evidence]
              + [(k, "CONTEXT", True) for k in context.get("optional", []) if k not in evidence])

    definitions = load_collectors(conn, [k for k, _, _ in wanted])
    node_targets = nodes or ([target] if target["target_type"] == "NODE" else [])

    plan = []
    for key, purpose, optional in wanted:
        definition = definitions.get(key)
        if definition is None:
            plan.append((target, key, purpose, optional))   # reported as NOT_COLLECTED
            continue
        if definition["execution_scope"] == "NODE":
            plan.extend((node, key, purpose, optional) for node in node_targets)
        else:
            plan.append((target, key, purpose, optional))
    return plan, definitions


# -----------------------------------------------------------------------------
# Queueing
# -----------------------------------------------------------------------------

def find_or_create_assignment(conn, target_id, definition, optional):
    """(assignment_id, None) or (None, reason). Creates an ON_DEMAND assignment if a connection fits."""
    row = conn.execute(
        "SELECT assignment_id, is_enabled FROM keystone.collector_assignment "
        "WHERE target_id = %s AND collector_id = %s ORDER BY assignment_id LIMIT 1",
        (target_id, definition["collector_id"]),
    ).fetchone()
    if row is not None:
        if not row["is_enabled"]:
            return None, "assignment is disabled"
        return row["assignment_id"], None
    if optional:
        return None, "not assigned (optional)"

    host = definition["execution_type"] == "SSH"
    has_connection = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM keystone.target_connection WHERE target_id = %s "
        "AND is_active AND ((%s AND connection_purpose = 'HOST') "
        "OR (NOT %s AND connection_purpose <> 'HOST'))) AS ok",
        (target_id, host, host),
    ).fetchone()["ok"]
    if not has_connection:
        return None, f"no {'HOST' if host else 'database'} connection defined for this target"

    assignment_id = conn.execute(
        "INSERT INTO keystone.collector_assignment "
        "(collector_id, target_id, execution_mode, interval_seconds, is_enabled) "
        "VALUES (%s, %s, 'ON_DEMAND', NULL, TRUE) RETURNING assignment_id",
        (definition["collector_id"], target_id),
    ).fetchone()["assignment_id"]
    logger.info("Created ON_DEMAND assignment %s: %s on target %s.",
                assignment_id, definition["collector_key"], target_id)
    return assignment_id, None


def queue_task(conn, assignment_id):
    """Queue now; if the assignment already has an active task, follow that one."""
    row = conn.execute(
        "INSERT INTO keystone.collection_queue (assignment_id, status, scheduled_at) "
        "VALUES (%s, 'WAITING', clock_timestamp()) ON CONFLICT DO NOTHING RETURNING task_id",
        (assignment_id,),
    ).fetchone()
    if row is not None:
        return row["task_id"]
    return conn.execute(
        "SELECT task_id FROM keystone.collection_queue "
        "WHERE assignment_id = %s AND status IN ('WAITING', 'RUNNING')",
        (assignment_id,),
    ).fetchone()["task_id"]


def record_collection(conn, health_check_id, target_id, key, purpose,
                      assignment_id, task_id, status, message):
    return conn.execute(
        """
        INSERT INTO keystone.health_check_collection
            (health_check_id, target_id, collector_key, purpose, assignment_id,
             task_id, status, status_message)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING health_check_collection_id
        """,
        (health_check_id, target_id, key, purpose, assignment_id, task_id, status, message),
    ).fetchone()["health_check_collection_id"]


# -----------------------------------------------------------------------------
# Waiting
# -----------------------------------------------------------------------------

def collection_state(conn, task_ids):
    """{task_id: (state, seconds in current state, history_row)} for the tracked tasks."""
    queue = {
        r["task_id"]: r for r in conn.execute(
            "SELECT task_id, status, EXTRACT(EPOCH FROM clock_timestamp() "
            "- COALESCE(started_at, created_at)) AS running_seconds "
            "FROM keystone.collection_queue WHERE task_id = ANY(%s)", (list(task_ids),)
        ).fetchall()
    }
    history = {
        r["task_id"]: r for r in conn.execute(
            "SELECT DISTINCT ON (task_id) task_id, status, status_message, error_message "
            "FROM keystone.collector_run_history WHERE task_id = ANY(%s) "
            "ORDER BY task_id, finished_at DESC", (list(task_ids),)
        ).fetchall()
    }
    conn.commit()

    state = {}
    for task_id in task_ids:
        q = queue.get(task_id)
        if q is not None and q["status"] in ("WAITING", "RUNNING"):
            state[task_id] = (q["status"], q["running_seconds"], None)
        elif q is not None:   # e.g. RETRY_EXHAUSTED stays in the queue
            state[task_id] = ("DONE", None, history.get(task_id) or {"status": q["status"]})
        else:
            state[task_id] = ("DONE", None, history.get(task_id))
    return state


def wait_for_collections(connect, pool, task_ids, wait_seconds, stop_event=None):
    """Run the pool until every task finished or ran past wait_seconds; returns final states."""
    pending = set(task_ids)
    results = {}
    while pending and not (stop_event and stop_event.is_set()):
        pool.recover_if_due()
        pool.fill()
        with connect() as conn:
            state = collection_state(conn, pending)
        for task_id, (status, running, history) in state.items():
            if status == "DONE":
                results[task_id] = ("DONE", history)
                pending.discard(task_id)
            elif running is not None and running > wait_seconds:
                # Per collector: not started, or not finished, within the limit.
                results[task_id] = ("WAIT_LIMIT", status)
                pending.discard(task_id)
        if pending:
            time.sleep(POLL_SECONDS)
    return results


# -----------------------------------------------------------------------------
# Health check
# -----------------------------------------------------------------------------

def run_health_check(connect, target_id, assessment_key=None,
                     wait_minutes=DEFAULT_WAIT_MINUTES, process=None, requested_by=None):
    """Returns the health_check_id. Raises only if the health check itself cannot run."""
    with connect() as conn:
        target, nodes = load_target_tree(conn, target_id)
        assessment_keys = load_assessments(conn, target["provider"], assessment_key)
        health_check_id = conn.execute(
            "INSERT INTO keystone.health_check (target_id, status, requested_by) "
            "VALUES (%s, 'RUNNING', %s) RETURNING health_check_id",
            (target_id, requested_by),
        ).fetchone()["health_check_id"]
        conn.commit()

    logger.info("Health check %s: %s (%s node(s)), assessments: %s.",
                health_check_id, target["name"], len(nodes), ", ".join(assessment_keys),
                extra={"keystone_event": True,
                       "context": {"health_check_id": health_check_id, "target_id": target_id}})

    pool = None
    try:
        # 1. Plan and queue.
        tracked = {}   # task_id -> collection id
        with connect() as conn:
            plan, definitions = plan_collections(conn, target, nodes, assessment_keys)
            for plan_target, key, purpose, optional in plan:
                definition = definitions.get(key)
                if definition is None:
                    assignment_id, reason = None, "collector is not defined or not active"
                else:
                    assignment_id, reason = find_or_create_assignment(
                        conn, plan_target["target_id"], definition, optional)
                if assignment_id is None:
                    if not optional or reason != "not assigned (optional)":
                        record_collection(conn, health_check_id, plan_target["target_id"], key,
                                          purpose, None, None, "NOT_COLLECTED", reason)
                        logger.warning("Health check %s: %s on %s not collected: %s.",
                                       health_check_id, key, plan_target["name"], reason)
                    continue
                task_id = queue_task(conn, assignment_id)
                collection_id = record_collection(
                    conn, health_check_id, plan_target["target_id"], key, purpose,
                    assignment_id, task_id, "QUEUED", None)
                tracked[task_id] = collection_id
            conn.commit()

        # 2. Collect with our own worker pool (another agent may take some tasks; that is fine).
        logger.info("Health check %s: collecting %s task(s).", health_check_id, len(tracked))
        pool = WorkerPool(connect, f"healthcheck-{health_check_id}-{uuid.uuid4().hex[:8]}",
                          process=process)
        results = wait_for_collections(connect, pool, list(tracked), wait_minutes * 60)

        with connect() as conn:
            for task_id, (state, history) in results.items():
                if state == "WAIT_LIMIT":
                    status, message = "WAIT_LIMIT", (
                        f"{'Still running' if history == 'RUNNING' else 'Not started'} after "
                        f"{wait_minutes} min; assessed without waiting.")
                elif history is None:
                    status, message = "FAILED", "Task finished without a run history record."
                else:
                    status = history["status"]
                    message = history.get("error_message") or history.get("status_message")
                conn.execute(
                    "UPDATE keystone.health_check_collection SET status = %s, status_message = %s "
                    "WHERE health_check_collection_id = %s",
                    (status, message, tracked[task_id]))
            conn.commit()

        # 3. Assess the SYSTEM target with the evidence now in the repository.
        for key in assessment_keys:
            with connect() as conn:
                try:
                    assessment_engine.run_assessment(conn, key, target_id,
                                                     health_check_id=health_check_id)
                except Exception:
                    logger.error("Health check %s: assessment %s failed.", health_check_id, key,
                                 exc_info=True)

        with connect() as conn:
            conn.execute(
                "UPDATE keystone.health_check SET status = 'COMPLETED', "
                "finished_at = clock_timestamp() WHERE health_check_id = %s",
                (health_check_id,))
            conn.commit()

    except Exception as exc:
        logger.error("Health check %s failed: %s", health_check_id, exc, exc_info=True)
        with connect() as conn:
            conn.execute(
                "UPDATE keystone.health_check SET status = 'FAILED', finished_at = clock_timestamp(), "
                "status_message = %s WHERE health_check_id = %s",
                (f"{type(exc).__name__}: {exc}", health_check_id))
            conn.commit()
        raise
    finally:
        if pool is not None:
            # A collector past the wait limit still finishes (statement_timeout bounds it).
            if pool.running_count:
                logger.info("Waiting for %s collector(s) still running before exit.",
                            pool.running_count)
            pool.executor.shutdown(wait=True)

    return health_check_id


# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

def load_summary(conn, health_check_id):
    check = conn.execute(
        "SELECT hc.*, t.name AS target_name FROM keystone.health_check hc "
        "JOIN keystone.target t USING (target_id) WHERE health_check_id = %s",
        (health_check_id,)).fetchone()
    collections = conn.execute(
        "SELECT t.name AS target_name, c.collector_key, c.purpose, c.status, c.status_message "
        "FROM keystone.health_check_collection c JOIN keystone.target t USING (target_id) "
        "WHERE c.health_check_id = %s ORDER BY c.purpose DESC, c.collector_key, t.name",
        (health_check_id,)).fetchall()
    results = conn.execute(
        """
        SELECT ad.assessment_key, rd.rule_key, rd.name AS rule_name, res.outcome,
               res.max_severity, res.reason
        FROM keystone.assessment_run ar
        JOIN keystone.assessment_definition ad ON ad.assessment_id = ar.assessment_id
        JOIN keystone.assessment_result res ON res.assessment_run_id = ar.assessment_run_id
        JOIN keystone.rule_definition rd ON rd.rule_id = res.rule_id
        WHERE ar.health_check_id = %s
        ORDER BY ad.assessment_key, rd.rule_key
        """, (health_check_id,)).fetchall()
    conn.commit()
    return check, collections, results


def print_summary(conn, health_check_id):
    check, collections, results = load_summary(conn, health_check_id)
    lines = ["", f"Health check {health_check_id} - {check['target_name']} - {check['status']}", "",
             "Collections:"]
    for c in collections:
        note = f"  ({c['status_message']})" if c["status_message"] else ""
        lines.append(f"  {c['purpose']:<8} {c['collector_key']:<28} {c['target_name']:<14} "
                     f"{c['status']}{note}")
    lines += ["", "Rules:"]
    for r in results:
        severity = f" {r['max_severity']}" if r["max_severity"] else ""
        reason = f"  ({r['reason']})" if r["reason"] and r["outcome"] != "ATTENTION_REQUIRED" else ""
        lines.append(f"  {r['rule_key']:<12} {r['outcome']}{severity}  {r['rule_name']}{reason}")
    print("\n".join(lines))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m repository.healthcheck.health_check",
        description="Collect the evidence the assessments need, then assess (one-off).",
    )
    parser.add_argument("--target", type=int, required=True, help="target_id (SYSTEM includes its nodes)")
    parser.add_argument("--assessment", help="only this assessment_key (default: all enabled)")
    parser.add_argument("--wait-minutes", type=int, default=DEFAULT_WAIT_MINUTES,
                        help=f"per-collector wait limit (default: {DEFAULT_WAIT_MINUTES})")
    parser.add_argument("--report", choices=["tr", "en"],
                        help="also write the HTML report in this language")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    configure_logging("health_check", connect=worker.connect_repository)

    try:
        user = getpass.getuser()
    except Exception:
        user = None
    health_check_id = run_health_check(worker.connect_repository, args.target,
                                       args.assessment, args.wait_minutes, requested_by=user)
    with worker.connect_repository() as conn:
        print_summary(conn, health_check_id)
        if args.report:
            from repository.report.health_check_report import write_report
            path = write_report(conn, health_check_id, args.report)
            print(f"\nReport: {path.resolve()}")


if __name__ == "__main__":
    main()
