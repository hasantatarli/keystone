# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
import uuid
import threading
import psycopg
import time
import paramiko

from psycopg.rows import dict_row
from repository.common.credentials import decrypt_credential
from concurrent.futures import ThreadPoolExecutor, as_completed
from psycopg.errors import QueryCanceled
from psycopg import OperationalError

class TaskOwnershipLost(RuntimeError):
    pass

# -----------------------------------------------------------------------------
# Constants 
# -----------------------------------------------------------------------------
MAX_RETRY_COUNT = 3

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
REPOSITORY_CONFIG = {
    "host": os.getenv("KEYSTONE_REPOSITORY_HOST", "localhost"),
    "port": int(os.getenv("KEYSTONE_REPOSITORY_PORT", "5432")),
    "dbname": os.getenv("KEYSTONE_REPOSITORY_DB", "keystone_lab"),
    "user": os.getenv("KEYSTONE_REPOSITORY_USER", "postgres"),
    "password": os.getenv("KEYSTONE_REPOSITORY_PASSWORD")
}

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# -----------------------------------------------------------------------------
# Repository Connection
# -----------------------------------------------------------------------------

def connect_repository():
    return psycopg.connect(
        **REPOSITORY_CONFIG,
        row_factory=dict_row
    )


# -----------------------------------------------------------------------------
# Target Connection
# -----------------------------------------------------------------------------

def connect_target(task, database_name=None):
    password = resolve_password(task)

    conn=  psycopg.connect(
        host=task["host"],
        port=task["port"],
        dbname=database_name or task["database_name"],
        user=task["username"],
        password=password,
        connect_timeout=10,
        row_factory=dict_row,
    )

    with conn.cursor() as cur:
        cur.execute(
            "SET statement_timeout = '300s';"
        )

    return conn

def connect_ssh_target(task):
    password = resolve_password(task)

    client = paramiko.SSHClient()

    client.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
    )

    client.connect(
        hostname=task["host"],
        port=task["port"] or 22,
        username=task["username"],
        password=password,
        timeout=15,
        banner_timeout=15,
        auth_timeout=15
    )

    return client

# -----------------------------------------------------------------------------
# Credential Management
# -----------------------------------------------------------------------------

def resolve_password(task):
    auth_type = task["auth_type"].upper()

    if auth_type == "PASSWORD":
        return decrypt_credential(
            task["credential_data"]
        )

    raise RuntimeError(
        f"Unsupported authentication type: {auth_type}"
    )

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------

def calculate_checksum(file_path):
    sha256 = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


# -----------------------------------------------------------------------------
# Queue Management
# -----------------------------------------------------------------------------
def claim_tasks(conn, worker_id, limit=5):
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH next_tasks AS
            (
                SELECT q.task_id
                FROM keystone.collection_queue q
                JOIN keystone.collector_assignment ca
                    ON ca.assignment_id = q.assignment_id
                JOIN keystone.collector_definition cd
                    ON cd.collector_id = ca.collector_id
                JOIN keystone.target t
                    ON t.target_id = ca.target_id
                WHERE q.status = 'WAITING'
                  AND q.scheduled_at <= clock_timestamp()
                  AND ca.is_enabled = TRUE
                  AND cd.is_active = TRUE
                  AND t.is_active = TRUE
                ORDER BY
                    q.scheduled_at,
                    q.task_id
                FOR UPDATE OF q SKIP LOCKED
                LIMIT %s
            )
            UPDATE keystone.collection_queue q
            SET
                status = 'RUNNING',
                started_at = clock_timestamp(),
                worker_id = %s,
                heartbeat_at = clock_timestamp()
            FROM next_tasks nt
            WHERE q.task_id = nt.task_id
            RETURNING q.task_id;
            """,
            (limit,worker_id),
        )

        claimed = cur.fetchall()

        if not claimed:
            conn.commit()
            return []

        task_ids = [
            row["task_id"]
            for row in claimed
        ]

        cur.execute(
            """
            SELECT
                q.task_id,
                q.assignment_id,
                q.started_at,
                q.worker_id,
                q.heartbeat_at,
                ca.collector_id,
                cd.collector_key,
                cd.name AS collector_name,
                cd.script_file,
                cd.execution_scope,
                cd.execution_type,
                cd.checksum,
                cd.component,
                t.target_id,
                t.name AS target_name,
                t.provider,
                t.target_type,
                tc.connection_id,
                tc.host,
                tc.port,
                tc.database_name,
                tc.username,
                tc.auth_type,
                tc.credential_data

            FROM keystone.collection_queue q

            JOIN keystone.collector_assignment ca
                ON ca.assignment_id = q.assignment_id

            JOIN keystone.collector_definition cd
                ON cd.collector_id = ca.collector_id

            JOIN keystone.target t
                ON t.target_id = ca.target_id

            JOIN keystone.target_connection tc
                ON tc.target_id = t.target_id
            AND tc.is_active = TRUE
            AND
            (
                (cd.execution_type = 'SQL'
                    AND tc.connection_purpose <> 'HOST')
                OR
                (cd.execution_type = 'SSH'
                    AND tc.connection_purpose = 'HOST')
            )

            WHERE q.task_id = ANY(%s)

            ORDER BY q.task_id;
            """,
            (task_ids,),
        )

        tasks = cur.fetchall()

    conn.commit()

    return tasks

def remove_task(conn, task_id, worker_id):
    sql = """
        DELETE FROM keystone.collection_queue
        WHERE task_id = %(task_id)s
          AND status = 'RUNNING'
          AND worker_id = %(worker_id)s;
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "task_id": task_id,
                "worker_id": worker_id,
            }
        )

        deleted_count = cur.rowcount

    #conn.commit()

    return deleted_count

def get_stale_tasks(conn, stale_after_seconds=90):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                q.task_id,
                q.assignment_id,
                q.status,
                q.started_at,
                q.worker_id,
                q.heartbeat_at,
                clock_timestamp() - q.heartbeat_at AS heartbeat_age
            FROM keystone.collection_queue q
            WHERE q.status = 'RUNNING'
              AND q.heartbeat_at IS NOT NULL
              AND q.heartbeat_at <
                  clock_timestamp()
                  - (%s * INTERVAL '1 second')
            ORDER BY q.heartbeat_at;
            """,
            (stale_after_seconds,),
        )

        return cur.fetchall()


def recover_stale_tasks(
    conn,
    stale_after_seconds=90,
    max_retry_count=MAX_RETRY_COUNT
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                q.task_id,
                q.assignment_id,
                q.started_at,
                q.worker_id,
                q.retry_count
            FROM keystone.collection_queue q
            WHERE q.status = 'RUNNING'
              AND q.heartbeat_at IS NOT NULL
              AND q.heartbeat_at <
                  clock_timestamp()
                  - (%s * INTERVAL '1 second')
            FOR UPDATE;
            """,
            (stale_after_seconds,),
        )

        stale_tasks = cur.fetchall()
        recovered = []

        for task in stale_tasks:
            cur.execute(
                """
                INSERT INTO keystone.collector_run_history
                (
                    assignment_id,
                    task_id,
                    started_at,
                    finished_at,
                    status,
                    execution_time_ms,
                    rows_collected,
                    executed_by,
                    status_message,
                    error_message
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    clock_timestamp(),
                    'STALE',
                    (
                        EXTRACT(
                            EPOCH FROM (clock_timestamp() - %s)
                        ) * 1000
                    )::bigint,
                    NULL,
                    %s,
                    'Worker heartbeat expired.',
                    NULL
                );
                """,
                (
                    task["assignment_id"],
                    task["task_id"],
                    task["started_at"],
                    task["started_at"],
                    task["worker_id"],
                ),
            )

            if task["retry_count"] >= max_retry_count:
                cur.execute(
                    """
                    UPDATE keystone.collection_queue
                    SET
                        status = 'RETRY_EXHAUSTED',
                        worker_id = NULL,
                        heartbeat_at = NULL,
                        status_message = 'Maximum retry count reached.'
                    WHERE task_id = %s
                      AND status = 'RUNNING';
                    """,
                    (task["task_id"],),
                )

                recovered.append(
                    {
                        "task_id": task["task_id"],
                        "assignment_id": task["assignment_id"],
                        "retry_count": task["retry_count"],
                        "status": "RETRY_EXHAUSTED",
                    }
                )

            else:
                cur.execute(
                    """
                    UPDATE keystone.collection_queue
                    SET
                        status = 'WAITING',
                        started_at = NULL,
                        worker_id = NULL,
                        heartbeat_at = NULL,
                        retry_count = retry_count + 1,
                        status_message =
                            'Recovered from stale RUNNING state.'
                    WHERE task_id = %s
                      AND status = 'RUNNING';
                    """,
                    (task["task_id"],),
                )

                recovered.append(
                    {
                        "task_id": task["task_id"],
                        "assignment_id": task["assignment_id"],
                        "retry_count": task["retry_count"] + 1,
                        "status": "WAITING",
                    }
                )

    conn.commit()
    return recovered


def update_task_heartbeat(task_id, worker_id):
    with connect_repository() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE keystone.collection_queue
                SET heartbeat_at = clock_timestamp()
                WHERE task_id = %s
                  AND status = 'RUNNING'
                  AND worker_id = %s;
                """,
                (
                    task_id,
                    worker_id
                ),
            )

        conn.commit()

def heartbeat_loop(
    task_id,
    worker_id,
    stop_event,
    interval_seconds=30
):
    while not stop_event.wait(interval_seconds):
        try:
            update_task_heartbeat(
                task_id,
                worker_id
            )
        except Exception as exc:
            print()
            print("HEARTBEAT UPDATE FAILED")
            print("-----------------------")
            print(f"Task ID : {task_id}")
            print(f"Error   : {exc}")        


def verify_task_ownership(conn, task_id, worker_id):
    sql = """
        SELECT task_id
        FROM keystone.collection_queue
        WHERE task_id = %(task_id)s
          AND status = 'RUNNING'
          AND worker_id = %(worker_id)s
        FOR UPDATE;
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "task_id": task_id,
                "worker_id": worker_id,
            }
        )

        return cur.fetchone() is not None
                
# -----------------------------------------------------------------------------
# Collector Execution
# -----------------------------------------------------------------------------

def execute_collector(task, target_conn):
    script_path = PROJECT_ROOT / task["script_file"]

    if not script_path.exists():
        raise RuntimeError(
            f"Collector script not found: {script_path}"
        )

    actual_checksum = calculate_checksum(script_path)
    expected_checksum = task["checksum"]

    if actual_checksum.lower() != expected_checksum.lower():
        raise RuntimeError(
            f"Collector integrity validation failed for "
            f"{task['collector_name']}. "
            f"Expected checksum: {expected_checksum}, "
            f"actual checksum: {actual_checksum}"
        )

    sql = script_path.read_text(encoding="utf-8")

    with target_conn.cursor(row_factory=dict_row) as cur:
        #cur.execute("SELECT pg_sleep(15);")
        cur.execute(sql)
        return cur.fetchall()


def execute_ssh_collector(task):
    script_path = PROJECT_ROOT / task["script_file"]

    if not script_path.exists():
        raise RuntimeError(
            f"Collector script not found: {script_path}"
        )

    actual_checksum = calculate_checksum(script_path)

    if actual_checksum != task["checksum"]:
        raise RuntimeError(
            f"Collector checksum mismatch: {task['collector_key']}"
        )

    script = script_path.read_text(
        encoding="utf-8"
    )

    client = connect_ssh_target(task)

    try:
        stdin, stdout, stderr = client.exec_command(
            script,
            timeout=60
        )

        exit_status = stdout.channel.recv_exit_status()

        output = stdout.read().decode(
            "utf-8",
            errors="replace"
        )

        error_output = stderr.read().decode(
            "utf-8",
            errors="replace"
        )

        if exit_status != 0:
            raise RuntimeError(
                f"SSH collector failed with exit status "
                f"{exit_status}: {error_output.strip()}"
            )

        return output

    finally:
        client.close()

# -----------------------------------------------------------------------------
# Database Discovery
# -----------------------------------------------------------------------------


def discover_databases(target_conn):
    sql = """
        SELECT
            oid AS database_oid,
            datname AS database_name
        FROM pg_database
        WHERE datallowconn = true
          AND datistemplate = false
        ORDER BY datname;
    """

    with target_conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        return cur.fetchall()

def execute_database_scoped_collector(task):
    rows = []
    errors = []

    captured_at = datetime.now(timezone.utc)

    system_conn = None

    try:
        system_conn = connect_target(task)
        databases = discover_databases(system_conn)

    finally:
        if system_conn is not None:
            system_conn.close()

    successful_database_count = 0

    for database in databases:
        database_name = database["database_name"]

        target_conn = None

        try:
            target_conn = connect_target(
                task,
                database_name=database_name,
            )

            database_rows = execute_collector(
                task,
                target_conn,
            )

            for row in database_rows:
                row["captured_at"] = captured_at

            rows.extend(database_rows)

            successful_database_count += 1

        except Exception as exc:
            errors.append(
                {
                    "database_name": database_name,
                    "error": str(exc),
                }
            )

        finally:
            if target_conn is not None:
                target_conn.close()

    execution_info = {
        "database_count": len(databases),
        "successful_database_count": successful_database_count,
        "failed_database_count": len(errors),
        "errors": errors,
    }

    return rows, execution_info

# -----------------------------------------------------------------------------
# Result Persistence
# -----------------------------------------------------------------------------



def save_instance_inventory(conn, task, rows):
    if not rows:
        raise RuntimeError(
            "Instance Inventory collector returned no rows."
        )

    if len(rows) != 1:
        raise RuntimeError(
            f"Instance Inventory collector returned {len(rows)} rows; expected 1."
        )

    row = rows[0]

    sql = """
        INSERT INTO postgresql.instance_inventory
        (
            target_id,
            server_version,
            server_version_num,
            server_address,
            server_port,
            current_database,
            collector_user,
            in_recovery,
            postmaster_start_time,
            system_identifier,
            last_collected_at
        )
        VALUES
        (
            %(target_id)s,
            %(server_version)s,
            %(server_version_num)s,
            %(server_address)s,
            %(server_port)s,
            %(current_database)s,
            %(collector_user)s,
            %(in_recovery)s,
            %(postmaster_start_time)s,
            %(system_identifier)s,
            %(last_collected_at)s
        )
        ON CONFLICT (target_id)
        DO UPDATE SET
            server_version        = EXCLUDED.server_version,
            server_version_num    = EXCLUDED.server_version_num,
            server_address        = EXCLUDED.server_address,
            server_port           = EXCLUDED.server_port,
            current_database      = EXCLUDED.current_database,
            collector_user        = EXCLUDED.collector_user,
            in_recovery           = EXCLUDED.in_recovery,
            postmaster_start_time = EXCLUDED.postmaster_start_time,
            system_identifier     = EXCLUDED.system_identifier,
            last_collected_at     = EXCLUDED.last_collected_at;
    """

    params = {
        "target_id": task["target_id"],
        "server_version": row["server_version"],
        "server_version_num": row["server_version_num"],
        "server_address": row["server_address"],
        "server_port": row["server_port"],
        "current_database": row["current_database"],
        "collector_user": row["collector_user"],
        "in_recovery": row["in_recovery"],
        "postmaster_start_time": row["postmaster_start_time"],
        "system_identifier": row["system_identifier"],
        "last_collected_at": row["collected_at"]
    }

    with conn.cursor() as cur:
        cur.execute(sql, params)

    #conn.commit()

def save_configuration_snapshot(conn, task, rows):
    if not rows:
        raise RuntimeError(
            "Configuration Snapshot collector returned no rows."
        )

    captured_at = rows[0]["captured_at"]

    for row in rows:
        if row["captured_at"] != captured_at:
            raise RuntimeError(
                "Configuration Snapshot returned multiple captured_at values."
            )

    data = [
        {
            "target_id": task["target_id"],
            "captured_at": row["captured_at"],
            "setting_name": row["setting_name"],
            "setting_value": row["setting_value"],
            "unit": row["unit"],
            "setting_type": row["setting_type"],
            "category": row["category"],
            "context": row["context"],
            "source": row["source"],
            "pending_restart": row["pending_restart"],
        }
        for row in rows
    ]

    sql = """
        INSERT INTO postgresql.configuration_snapshot
        (
            target_id,
            captured_at,
            setting_name,
            setting_value,
            unit,
            setting_type,
            category,
            context,
            source,
            pending_restart
        )
        VALUES
        (
            %(target_id)s,
            %(captured_at)s,
            %(setting_name)s,
            %(setting_value)s,
            %(unit)s,
            %(setting_type)s,
            %(category)s,
            %(context)s,
            %(source)s,
            %(pending_restart)s
        );
    """

    with conn.cursor() as cur:
        cur.executemany(sql, data)    

def save_database_snapshot(conn, task, rows):
    if not rows:
        raise RuntimeError(
            "Database Inventory & Capacity collector returned no rows."
        )

    captured_at = rows[0]["captured_at"]

    for row in rows:
        if row["captured_at"] != captured_at:
            raise RuntimeError(
                "Database Inventory & Capacity returned multiple captured_at values."
            )

    data = [
        {
            "target_id": task["target_id"],
            "captured_at": row["captured_at"],
            "database_oid": row["database_oid"],
            "database_name": row["database_name"],
            "database_owner": row["database_owner"],
            "encoding": row["encoding"],
            "collation_name": row["collation_name"],
            "ctype_name": row["ctype_name"],
            "connection_limit": row["connection_limit"],
            "allow_connections": row["allow_connections"],
            "is_template": row["is_template"],
            "database_size_bytes": row["database_size_bytes"],
            "tablespace_name": row["tablespace_name"],
        }
        for row in rows
    ]

    sql = """
        INSERT INTO postgresql.database_snapshot
        (
            target_id,
            captured_at,
            database_oid,
            database_name,
            database_owner,
            encoding,
            collation_name,
            ctype_name,
            connection_limit,
            allow_connections,
            is_template,
            database_size_bytes,
            tablespace_name
        )
        VALUES
        (
            %(target_id)s,
            %(captured_at)s,
            %(database_oid)s,
            %(database_name)s,
            %(database_owner)s,
            %(encoding)s,
            %(collation_name)s,
            %(ctype_name)s,
            %(connection_limit)s,
            %(allow_connections)s,
            %(is_template)s,
            %(database_size_bytes)s,
            %(tablespace_name)s
        );
    """

    with conn.cursor() as cur:
        cur.executemany(sql, data)

def save_table_capacity_snapshot(conn, task, rows):
    if not rows:
        return

    captured_at_values = {
        row["captured_at"]
        for row in rows
    }

    if len(captured_at_values) != 1:
        raise RuntimeError(
            "PG_TABLE_CAPACITY rows contain multiple captured_at values."
        )

    sql = """
        INSERT INTO postgresql.table_capacity_snapshot
        (
            target_id,
            captured_at,
            database_oid,
            database_name,
            schema_name,
            object_oid,
            object_name,
            object_type,
            is_partitioned,
            partition_count,
            tablespace_names,
            data_size_bytes,
            indexes_size_bytes,
            toast_size_bytes,
            total_size_bytes,
            estimated_rows,
            index_count
        )
        VALUES
        (
            %(target_id)s,
            %(captured_at)s,
            %(database_oid)s,
            %(database_name)s,
            %(schema_name)s,
            %(object_oid)s,
            %(object_name)s,
            %(object_type)s,
            %(is_partitioned)s,
            %(partition_count)s,
            %(tablespace_names)s,
            %(data_size_bytes)s,
            %(indexes_size_bytes)s,
            %(toast_size_bytes)s,
            %(total_size_bytes)s,
            %(estimated_rows)s,
            %(index_count)s
        );
    """

    params = []

    for row in rows:
        params.append(
            {
                "target_id": task["target_id"],
                "captured_at": row["captured_at"],
                "database_oid": row["database_oid"],
                "database_name": row["database_name"],
                "schema_name": row["schema_name"],
                "object_oid": row["object_oid"],
                "object_name": row["object_name"],
                "object_type": row["object_type"],
                "is_partitioned": row["is_partitioned"],
                "partition_count": row["partition_count"],
                "tablespace_names": row["tablespace_names"],
                "data_size_bytes": row["data_size_bytes"],
                "indexes_size_bytes": row["indexes_size_bytes"],
                "toast_size_bytes": row["toast_size_bytes"],
                "total_size_bytes": row["total_size_bytes"],
                "estimated_rows": row["estimated_rows"],
                "index_count": row["index_count"],
            }
        )

    with conn.cursor() as cur:
        cur.executemany(sql, params)
        
def save_vacuum_analyze_snapshot(conn, task, rows):
    if not rows:
        return

    captured_at_values = {
        row["captured_at"]
        for row in rows
    }

    if len(captured_at_values) != 1:
        raise RuntimeError(
            "PG_VACUUM_ANALYZE rows contain multiple captured_at values."
        )

    sql = """
        INSERT INTO postgresql.vacuum_analyze_snapshot
        (
            target_id,
            captured_at,

            database_oid,
            database_name,

            schema_name,
            object_oid,
            object_name,
            is_partition,

            n_live_tup,
            n_dead_tup,
            n_mod_since_analyze,
            n_ins_since_vacuum,

            last_vacuum,
            last_autovacuum,
            last_analyze,
            last_autoanalyze,

            vacuum_count,
            autovacuum_count,
            analyze_count,
            autoanalyze_count
        )
        VALUES
        (
            %(target_id)s,
            %(captured_at)s,

            %(database_oid)s,
            %(database_name)s,

            %(schema_name)s,
            %(object_oid)s,
            %(object_name)s,
            %(is_partition)s,

            %(n_live_tup)s,
            %(n_dead_tup)s,
            %(n_mod_since_analyze)s,
            %(n_ins_since_vacuum)s,

            %(last_vacuum)s,
            %(last_autovacuum)s,
            %(last_analyze)s,
            %(last_autoanalyze)s,

            %(vacuum_count)s,
            %(autovacuum_count)s,
            %(analyze_count)s,
            %(autoanalyze_count)s
        );
    """

    data = []

    for row in rows:
        data.append(
            {
                "target_id": task["target_id"],
                "captured_at": row["captured_at"],

                "database_oid": row["database_oid"],
                "database_name": row["database_name"],

                "schema_name": row["schema_name"],
                "object_oid": row["object_oid"],
                "object_name": row["object_name"],
                "is_partition": row["is_partition"],

                "n_live_tup": row["n_live_tup"],
                "n_dead_tup": row["n_dead_tup"],
                "n_mod_since_analyze": row["n_mod_since_analyze"],
                "n_ins_since_vacuum": row["n_ins_since_vacuum"],

                "last_vacuum": row["last_vacuum"],
                "last_autovacuum": row["last_autovacuum"],
                "last_analyze": row["last_analyze"],
                "last_autoanalyze": row["last_autoanalyze"],

                "vacuum_count": row["vacuum_count"],
                "autovacuum_count": row["autovacuum_count"],
                "analyze_count": row["analyze_count"],
                "autoanalyze_count": row["autoanalyze_count"],
            }
        )

    with conn.cursor() as cur:
        cur.executemany(sql, data)

def save_transaction_wraparound_snapshot(conn, task, rows):
    if not rows:
        raise RuntimeError(
            "PG_TRANSACTION_WRAPAROUND collector returned no rows."
        )

    captured_at_values = {
        row["captured_at"]
        for row in rows
    }

    if len(captured_at_values) != 1:
        raise RuntimeError(
            "PG_TRANSACTION_WRAPAROUND rows contain multiple captured_at values."
        )

    database_rows = []
    relation_rows = []

    for row in rows:
        record_type = row["record_type"]

        if record_type == "DATABASE":
            database_rows.append(row)

        elif record_type == "RELATION":
            relation_rows.append(row)

        else:
            raise RuntimeError(
                f"PG_TRANSACTION_WRAPAROUND returned unsupported "
                f"record_type: {record_type}"
            )

    if not database_rows:
        raise RuntimeError(
            "PG_TRANSACTION_WRAPAROUND returned no DATABASE rows."
        )

    database_names = [
        row["database_name"]
        for row in database_rows
    ]

    if len(database_names) != len(set(database_names)):
        raise RuntimeError(
            "PG_TRANSACTION_WRAPAROUND returned multiple DATABASE rows "
            "for the same database."
        )

    database_sql = """
        INSERT INTO postgresql.transaction_wraparound_snapshot
        (
            target_id,
            captured_at,
            database_oid,
            database_name,
            frozen_xid,
            xid_age,
            min_mxid,
            mxid_age
        )
        VALUES
        (
            %(target_id)s,
            %(captured_at)s,
            %(database_oid)s,
            %(database_name)s,
            %(frozen_xid)s::xid,
            %(xid_age)s,
            %(min_mxid)s::xid,
            %(mxid_age)s
        );
    """

    database_params = [
        {
            "target_id": task["target_id"],
            "captured_at": row["captured_at"],
            "database_oid": row["database_oid"],
            "database_name": row["database_name"],
            "frozen_xid": row["frozen_xid"],
            "xid_age": row["xid_age"],
            "min_mxid": row["min_mxid"],
            "mxid_age": row["mxid_age"],
        }
        for row in database_rows
    ]

    relation_sql = """
        INSERT INTO postgresql.relation_wraparound_snapshot
        (
            target_id,
            captured_at,
            database_oid,
            database_name,
            schema_name,
            object_oid,
            object_name,
            is_partition,
            frozen_xid,
            xid_age,
            min_mxid,
            mxid_age
        )
        VALUES
        (
            %(target_id)s,
            %(captured_at)s,
            %(database_oid)s,
            %(database_name)s,
            %(schema_name)s,
            %(object_oid)s,
            %(object_name)s,
            %(is_partition)s,
            %(frozen_xid)s::xid,
            %(xid_age)s,
            %(min_mxid)s::xid,
            %(mxid_age)s
        );
    """

    relation_params = [
        {
            "target_id": task["target_id"],
            "captured_at": row["captured_at"],
            "database_oid": row["database_oid"],
            "database_name": row["database_name"],
            "schema_name": row["schema_name"],
            "object_oid": row["object_oid"],
            "object_name": row["object_name"],
            "is_partition": row["is_partition"],
            "frozen_xid": row["frozen_xid"],
            "xid_age": row["xid_age"],
            "min_mxid": row["min_mxid"],
            "mxid_age": row["mxid_age"],
        }
        for row in relation_rows
    ]

    with conn.cursor() as cur:
        cur.executemany(
            database_sql,
            database_params
        )

        if relation_params:
            cur.executemany(
                relation_sql,
                relation_params
            )

def save_replication_status_snapshot(conn, task, rows):
    if not rows:
        raise RuntimeError(
            "PG_REPLICATION_STATUS collector returned no rows."
        )

    captured_at_values = {
        row["captured_at"]
        for row in rows
    }

    if len(captured_at_values) != 1:
        raise RuntimeError(
            "PG_REPLICATION_STATUS rows contain multiple captured_at values."
        )

    system_rows = []
    replica_rows = []

    for row in rows:
        record_type = row["record_type"]

        if record_type == "SYSTEM":
            system_rows.append(row)

        elif record_type == "REPLICA":
            replica_rows.append(row)

        else:
            raise RuntimeError(
                f"PG_REPLICATION_STATUS returned unsupported "
                f"record_type: {record_type}"
            )

    if len(system_rows) != 1:
        raise RuntimeError(
            f"PG_REPLICATION_STATUS returned {len(system_rows)} "
            f"SYSTEM rows; expected 1."
        )

    system_row = system_rows[0]

    if system_row["connected_replica_count"] != len(replica_rows):
        raise RuntimeError(
            "PG_REPLICATION_STATUS connected_replica_count does not "
            "match the number of REPLICA rows."
        )

    system_sql = """
        INSERT INTO postgresql.replication_status_snapshot
        (
            target_id,
            captured_at,
            current_wal_lsn,
            connected_replica_count
        )
        VALUES
        (
            %(target_id)s,
            %(captured_at)s,
            %(current_wal_lsn)s,
            %(connected_replica_count)s
        );
    """

    system_params = {
        "target_id": task["target_id"],
        "captured_at": system_row["captured_at"],
        "current_wal_lsn": system_row["current_wal_lsn"],
        "connected_replica_count": system_row["connected_replica_count"],
    }

    replica_sql = """
        INSERT INTO postgresql.replica_status_snapshot
        (
            target_id,
            captured_at,
            application_name,
            client_addr,
            client_port,
            backend_start,
            state,
            sync_state,
            sent_lsn,
            write_lsn,
            flush_lsn,
            replay_lsn,
            write_lag,
            flush_lag,
            replay_lag,
            reply_time,
            backend_xmin,
            current_wal_lsn
        )
        VALUES
        (
            %(target_id)s,
            %(captured_at)s,
            %(application_name)s,
            %(client_addr)s,
            %(client_port)s,
            %(backend_start)s,
            %(state)s,
            %(sync_state)s,
            %(sent_lsn)s,
            %(write_lsn)s,
            %(flush_lsn)s,
            %(replay_lsn)s,
            %(write_lag)s,
            %(flush_lag)s,
            %(replay_lag)s,
            %(reply_time)s,
            %(backend_xmin)s::xid,
            %(current_wal_lsn)s
        );
    """

    replica_params = [
        {
            "target_id": task["target_id"],
            "captured_at": row["captured_at"],
            "application_name": row["application_name"],
            "client_addr": row["client_addr"],
            "client_port": row["client_port"],
            "backend_start": row["backend_start"],
            "state": row["state"],
            "sync_state": row["sync_state"],
            "sent_lsn": row["sent_lsn"],
            "write_lsn": row["write_lsn"],
            "flush_lsn": row["flush_lsn"],
            "replay_lsn": row["replay_lsn"],
            "write_lag": row["write_lag"],
            "flush_lag": row["flush_lag"],
            "replay_lag": row["replay_lag"],
            "reply_time": row["reply_time"],
            "backend_xmin": row["backend_xmin"],
            "current_wal_lsn": row["current_wal_lsn"],
        }
        for row in replica_rows
    ]

    with conn.cursor() as cur:
        cur.execute(
            system_sql,
            system_params
        )

        if replica_params:
            cur.executemany(
                replica_sql,
                replica_params
            )

def save_replication_slot_snapshot(conn, task, rows):
    if not rows:
        return

    captured_at_values = {
        row["captured_at"]
        for row in rows
    }

    if len(captured_at_values) != 1:
        raise RuntimeError(
            "PG_REPLICATION_SLOTS rows contain multiple captured_at values."
        )

    sql = """
        INSERT INTO postgresql.replication_slot_snapshot
        (
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
        )
        VALUES
        (
            %(target_id)s,
            %(captured_at)s,
            %(slot_name)s,
            %(plugin)s,
            %(slot_type)s,
            %(database_name)s,
            %(temporary)s,
            %(active)s,
            %(active_pid)s,
            %(slot_xmin)s::xid,
            %(catalog_xmin)s::xid,
            %(restart_lsn)s,
            %(confirmed_flush_lsn)s,
            %(wal_status)s,
            %(safe_wal_size)s,
            %(two_phase)s,
            %(conflicting)s,
            %(invalidation_reason)s,
            %(failover)s
        );
    """

    params = [
        {
            "target_id": task["target_id"],
            "captured_at": row["captured_at"],
            "slot_name": row["slot_name"],
            "plugin": row["plugin"],
            "slot_type": row["slot_type"],
            "database_name": row["database"],
            "temporary": row["temporary"],
            "active": row["active"],
            "active_pid": row["active_pid"],
            "slot_xmin": row["slot_xmin"],
            "catalog_xmin": row["catalog_xmin"],
            "restart_lsn": row["restart_lsn"],
            "confirmed_flush_lsn": row["confirmed_flush_lsn"],
            "wal_status": row["wal_status"],
            "safe_wal_size": row["safe_wal_size"],
            "two_phase": row["two_phase"],
            "conflicting": row["conflicting"],
            "invalidation_reason": row["invalidation_reason"],
            "failover": row["failover"],
        }
        for row in rows
    ]

    with conn.cursor() as cur:
        cur.executemany(
            sql,
            params
        )

def save_connection_activity_snapshot(conn, task, rows):
    if not rows:
        return

    system_rows = [
        row for row in rows
        if row["record_type"] == "SYSTEM"
    ]

    database_rows = [
        row for row in rows
        if row["record_type"] == "DATABASE"
    ]

    breakdown_rows = [
        row for row in rows
        if row["record_type"] == "BREAKDOWN"
    ]

    target_id = task["target_id"]

    with conn.cursor() as cur:

        # ---------------------------------------------------------------------
        # SYSTEM
        # ---------------------------------------------------------------------
        for row in system_rows:
            cur.execute(
                """
                INSERT INTO postgresql.connection_activity_snapshot
                (
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
                )
                VALUES
                (
                    %s,
                    %s,

                    %s,
                    %s,
                    %s,
                    %s,
                    %s,

                    %s,
                    %s,
                    %s
                )
                """,
                (
                    target_id,
                    row["captured_at"],

                    row["current_connections"],
                    row["active_connections"],
                    row["idle_connections"],
                    row["idle_in_transaction_connections"],
                    row["idle_in_transaction_aborted_connections"],

                    row["oldest_idle_state_change"],
                    row["oldest_idle_in_transaction_state_change"],
                    row[
                        "oldest_idle_in_transaction_aborted_state_change"
                    ],
                ),
            )

        # ---------------------------------------------------------------------
        # DATABASE
        # ---------------------------------------------------------------------
        for row in database_rows:
            cur.execute(
                """
                INSERT INTO postgresql.connection_database_snapshot
                (
                    target_id,
                    captured_at,

                    database_oid,
                    database_name,

                    sessions,
                    sessions_abandoned,
                    sessions_fatal,
                    sessions_killed,

                    session_time,
                    active_time,
                    idle_in_transaction_time,

                    stats_reset,

                    current_connections,
                    active_connections,
                    idle_connections,
                    idle_in_transaction_connections,
                    idle_in_transaction_aborted_connections
                )
                VALUES
                (
                    %s,
                    %s,

                    %s,
                    %s,

                    %s,
                    %s,
                    %s,
                    %s,

                    %s,
                    %s,
                    %s,

                    %s,

                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    target_id,
                    row["captured_at"],

                    row["database_oid"],
                    row["database_name"],

                    row["sessions"],
                    row["sessions_abandoned"],
                    row["sessions_fatal"],
                    row["sessions_killed"],

                    row["session_time"],
                    row["active_time"],
                    row["idle_in_transaction_time"],

                    row["stats_reset"],

                    row["current_connections"],
                    row["active_connections"],
                    row["idle_connections"],
                    row["idle_in_transaction_connections"],
                    row[
                        "idle_in_transaction_aborted_connections"
                    ],
                ),
            )

        # ---------------------------------------------------------------------
        # BREAKDOWN
        # ---------------------------------------------------------------------
        for row in breakdown_rows:
            cur.execute(
                """
                INSERT INTO postgresql.connection_breakdown_snapshot
                (
                    target_id,
                    captured_at,

                    breakdown_type,
                    dimension_value,
                    state,
                    connection_count
                )
                VALUES
                (
                    %s,
                    %s,

                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    target_id,
                    row["captured_at"],

                    row["breakdown_type"],
                    row["dimension_value"],
                    row["state"],
                    row["connection_count"],
                ),
            )        

COLLECTOR_HANDLERS = {
    "PG_INSTANCE_INVENTORY": save_instance_inventory,
    "PG_CONFIGURATION_SNAPSHOT": save_configuration_snapshot,
    "PG_DATABASE_INVENTORY": save_database_snapshot,
    "PG_TABLE_CAPACITY": save_table_capacity_snapshot,
    "PG_VACUUM_ANALYZE": save_vacuum_analyze_snapshot,
    "PG_TRANSACTION_WRAPAROUND": save_transaction_wraparound_snapshot,
    "PG_REPLICATION_STATUS": save_replication_status_snapshot,
    "PG_REPLICATION_SLOTS": save_replication_slot_snapshot,
    "PG_CONNECTION_ACTIVITY": save_connection_activity_snapshot,
}

def persist_collector_result(conn, task, rows):
    collector_key = task["collector_key"]

    handler = COLLECTOR_HANDLERS.get(collector_key)

    if handler is None:
        raise RuntimeError(
            f"No persistence handler registered for collector: {collector_key}"
        )

    handler(conn, task, rows)
# -----------------------------------------------------------------------------
# Run History
# -----------------------------------------------------------------------------

def write_run_history(
    conn,
    task,
    started_at,
    finished_at,
    status,
    rows_collected=None,
    status_message=None,
    error_message=None
):
    execution_time_ms = int(
        (finished_at - started_at).total_seconds() * 1000
    )

    sql = """
        INSERT INTO keystone.collector_run_history
        (
            assignment_id,
            task_id,
            started_at,
            finished_at,
            status,
            execution_time_ms,
            rows_collected,
            executed_by,
            status_message,
            error_message
        )
        VALUES
        (
            %(assignment_id)s,
            %(task_id)s,
            %(started_at)s,
            %(finished_at)s,
            %(status)s,
            %(execution_time_ms)s,
            %(rows_collected)s,
            %(executed_by)s,
            %(status_message)s,
            %(error_message)s
        );
    """

    params = {
        "assignment_id": task["assignment_id"],
        "task_id": task["task_id"],
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "execution_time_ms": execution_time_ms,
        "rows_collected": rows_collected,
        "executed_by": task["worker_id"],
        "status_message": status_message,
        "error_message": error_message
    }

    with conn.cursor() as cur:
        cur.execute(sql, params)

    #conn.commit()

def process_task(task):
    stop_heartbeat = threading.Event()

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(
            task["task_id"],
            task["worker_id"],
            stop_heartbeat,
        ),
        daemon=True,
    )

    heartbeat_thread.start()

    try:
        with connect_repository() as conn:
            print()
            print(f"Task ID       : {task['task_id']}")
            print(f"Assignment ID : {task['assignment_id']}")
            print(
                f"Collector     : {task['component']} "
                f"- {task['collector_name']}"
            )
            print(f"Script        : {task['script_file']}")
            print(
                f"Target        : {task['target_id']} "
                f"- {task['target_name']}"
            )
            print(f"Provider      : {task['provider']}")
            print(f"Target Type   : {task['target_type']}")
            print(f"Connection    : {task['host']}:{task['port']}")
            print(f"Database      : {task['database_name']}")
            print(f"Username      : {task['username']}")

            started_at = task["started_at"]

            print()
            print("Executing collector...")

            # ============================================================
            # PHASE 1 - TARGET / COLLECTOR EXECUTION
            # ============================================================
            try:
                execution_info = None
                run_status = "SUCCESS"
                status_message = None

                if task["execution_type"] == "SSH":
                    rows = execute_ssh_collector(task)

                elif task["execution_scope"] == "DATABASE":
                    rows, execution_info = execute_database_scoped_collector(task)

                else:
                    with connect_target(task) as target_conn:
                        rows = execute_collector(
                            task,
                            target_conn,
                        )

                if execution_info is not None:
                    database_count = execution_info["database_count"]
                    successful_count = execution_info["successful_database_count"]
                    failed_count = execution_info["failed_database_count"]

                    if successful_count == 0:
                        raise RuntimeError(
                            f"DATABASE-scoped collector failed for all "
                            f"{database_count} database(s)."
                        )

                    if failed_count > 0:
                        run_status = "PARTIAL_SUCCESS"
                        status_message = (
                            f"Collector succeeded for {successful_count}/{database_count} "
                            f"database(s); {failed_count} database(s) failed."
                        )

            except QueryCanceled as exc:
                conn.rollback()

                if not verify_task_ownership(
                    conn,
                    task["task_id"],
                    task["worker_id"],
                ):
                    conn.rollback()

                    print()
                    print("TASK OWNERSHIP LOST")
                    print("-------------------")
                    print(f"Task ID : {task['task_id']}")
                    print(f"Worker  : {task['worker_id']}")
                    print(
                        "Error   : Ownership lost before "
                        "TIMEOUT persistence."
                    )
                    return

                finished_at = datetime.now(timezone.utc)

                try:
                    write_run_history(
                        conn=conn,
                        task=task,
                        started_at=started_at,
                        finished_at=finished_at,
                        status="TIMEOUT",
                        rows_collected=None,
                        status_message="Collector execution timed out.",
                        error_message=str(exc),
                    )

                    deleted_count = remove_task(
                        conn,
                        task["task_id"],
                        task["worker_id"],
                    )

                    if deleted_count != 1:
                        raise TaskOwnershipLost(
                            f"Task ownership lost before TIMEOUT completion. "
                            f"Task ID: {task['task_id']}"
                        )

                    conn.commit()

                except TaskOwnershipLost as ownership_exc:
                    conn.rollback()

                    print()
                    print("TASK OWNERSHIP LOST")
                    print("-------------------")
                    print(f"Task ID : {task['task_id']}")
                    print(f"Worker  : {task['worker_id']}")
                    print(f"Error   : {ownership_exc}")
                    return

                except Exception as repo_exc:
                    conn.rollback()

                    print()
                    print("REPOSITORY FINALIZATION FAILED")
                    print("------------------------------")
                    print(f"Task ID : {task['task_id']}")
                    print(f"Worker  : {task['worker_id']}")
                    print(f"Error   : {repo_exc}")

                    raise

                print()
                print("COLLECTOR EXECUTION TIMEOUT")
                print("---------------------------")
                print(f"Task ID   : {task['task_id']}")
                print(f"Collector : {task['collector_name']}")
                print(f"Target    : {task['target_name']}")
                print("Timeout   : 300 seconds")
                print(f"Error     : {exc}")
                return

            except OperationalError as exc:
                conn.rollback()

                if not verify_task_ownership(
                    conn,
                    task["task_id"],
                    task["worker_id"],
                ):
                    conn.rollback()

                    print()
                    print("TASK OWNERSHIP LOST")
                    print("-------------------")
                    print(f"Task ID : {task['task_id']}")
                    print(f"Worker  : {task['worker_id']}")
                    print(
                        "Error   : Ownership lost before "
                        "CONNECTION_FAILED persistence."
                    )
                    return

                finished_at = datetime.now(timezone.utc)

                try:
                    write_run_history(
                        conn=conn,
                        task=task,
                        started_at=started_at,
                        finished_at=finished_at,
                        status="CONNECTION_FAILED",
                        rows_collected=None,
                        status_message="Target connection failed.",
                        error_message=str(exc),
                    )

                    deleted_count = remove_task(
                        conn,
                        task["task_id"],
                        task["worker_id"],
                    )

                    if deleted_count != 1:
                        raise TaskOwnershipLost(
                            f"Task ownership lost before "
                            f"CONNECTION_FAILED completion. "
                            f"Task ID: {task['task_id']}"
                        )

                    conn.commit()

                except TaskOwnershipLost as ownership_exc:
                    conn.rollback()

                    print()
                    print("TASK OWNERSHIP LOST")
                    print("-------------------")
                    print(f"Task ID : {task['task_id']}")
                    print(f"Worker  : {task['worker_id']}")
                    print(f"Error   : {ownership_exc}")
                    return

                except Exception as repo_exc:
                    conn.rollback()

                    print()
                    print("REPOSITORY FINALIZATION FAILED")
                    print("------------------------------")
                    print(f"Task ID : {task['task_id']}")
                    print(f"Worker  : {task['worker_id']}")
                    print(f"Error   : {repo_exc}")

                    raise

                print()
                print("TARGET CONNECTION FAILED")
                print("------------------------")
                print(f"Task ID   : {task['task_id']}")
                print(f"Collector : {task['collector_name']}")
                print(f"Target    : {task['target_name']}")
                print(f"Error     : {exc}")
                return

            except Exception as exc:
                conn.rollback()

                if not verify_task_ownership(
                    conn,
                    task["task_id"],
                    task["worker_id"],
                ):
                    conn.rollback()

                    print()
                    print("TASK OWNERSHIP LOST")
                    print("-------------------")
                    print(f"Task ID : {task['task_id']}")
                    print(f"Worker  : {task['worker_id']}")
                    print(
                        "Error   : Ownership lost before "
                        "FAILED persistence."
                    )
                    return

                finished_at = datetime.now(timezone.utc)

                try:
                    write_run_history(
                        conn=conn,
                        task=task,
                        started_at=started_at,
                        finished_at=finished_at,
                        status="FAILED",
                        rows_collected=None,
                        status_message="Collector execution failed.",
                        error_message=str(exc),
                    )

                    deleted_count = remove_task(
                        conn,
                        task["task_id"],
                        task["worker_id"],
                    )

                    if deleted_count != 1:
                        raise TaskOwnershipLost(
                            f"Task ownership lost before FAILED completion. "
                            f"Task ID: {task['task_id']}"
                        )

                    conn.commit()

                except TaskOwnershipLost as ownership_exc:
                    conn.rollback()

                    print()
                    print("TASK OWNERSHIP LOST")
                    print("-------------------")
                    print(f"Task ID : {task['task_id']}")
                    print(f"Worker  : {task['worker_id']}")
                    print(f"Error   : {ownership_exc}")
                    return

                except Exception as repo_exc:
                    conn.rollback()

                    print()
                    print("REPOSITORY FINALIZATION FAILED")
                    print("------------------------------")
                    print(f"Task ID : {task['task_id']}")
                    print(f"Worker  : {task['worker_id']}")
                    print(f"Error   : {repo_exc}")

                    raise

                print()
                print("COLLECTOR EXECUTION FAILED")
                print("--------------------------")
                print(f"Task ID   : {task['task_id']}")
                print(f"Collector : {task['collector_name']}")
                print(f"Target    : {task['target_name']}")
                print(f"Error     : {exc}")
                return

           
            # ============================================================
            # PHASE 2 - SUCCESS / REPOSITORY FINALIZATION
            # ============================================================
            try:
                if not verify_task_ownership(
                    conn,
                    task["task_id"],
                    task["worker_id"],
                ):
                    raise TaskOwnershipLost(
                        f"Task ownership lost before result persistence. "
                        f"Task ID: {task['task_id']}"
                    )
                
                #raise RuntimeError("TEST repository finalization failure")
            
                persist_collector_result(
                    conn,
                    task,
                    rows,
                )

                finished_at = datetime.now(timezone.utc)

                write_run_history(
                    conn=conn,
                    task=task,
                    started_at=started_at,
                    finished_at=finished_at,
                    status=run_status,
                    rows_collected=len(rows),
                    status_message=status_message,
                )

                deleted_count = remove_task(
                    conn,
                    task["task_id"],
                    task["worker_id"],
                )

                if deleted_count != 1:
                    raise TaskOwnershipLost(
                        f"Task ownership lost before completion. "
                        f"Task ID: {task['task_id']}"
                    )

                conn.commit()

                print(
                    f"Collector returned {len(rows)} row(s)."
                )

                for row in rows:
                    print(row)

            except TaskOwnershipLost as exc:
                conn.rollback()

                print()
                print("TASK OWNERSHIP LOST")
                print("-------------------")
                print(f"Task ID : {task['task_id']}")
                print(f"Worker  : {task['worker_id']}")
                print(f"Error   : {exc}")

            except Exception as exc:
                conn.rollback()

                print()
                print("REPOSITORY FINALIZATION FAILED")
                print("------------------------------")
                print(f"Task ID : {task['task_id']}")
                print(f"Worker  : {task['worker_id']}")
                print(f"Error   : {exc}")

                raise

    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(
            timeout=5
        )

def finalize_failed_task(
    conn,
    task,
    started_at,
    finished_at,
    status,
    status_message,
    error_message
):
    if not verify_task_ownership(
        conn,
        task["task_id"],
        task["worker_id"]
    ):
        raise TaskOwnershipLost(
            f"Task ownership lost before failure persistence. "
            f"Task ID: {task['task_id']}"
        )

    write_run_history(
        conn=conn,
        task=task,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        rows_collected=None,
        status_message=status_message,
        error_message=error_message
    )

    deleted_count = remove_task(
        conn,
        task["task_id"],
        task["worker_id"]
    )

    if deleted_count != 1:
        raise TaskOwnershipLost(
            f"Task ownership lost before failure completion. "
            f"Task ID: {task['task_id']}"
        )

    conn.commit()        
# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    print()
    print("Keystone Worker")
    print("===============")
    print()

    max_workers = 5
    worker_id = str(uuid.uuid4())

    print(f"Worker ID : {worker_id}")
    print()


    with connect_repository() as conn:
        stale_tasks = get_stale_tasks(conn)
        
    if stale_tasks:
        print(
            f"{len(stale_tasks)} stale task(s) found."
        )

        for task in stale_tasks:
            print(
                f"Task {task['task_id']} "
                f"-> heartbeat age {task['heartbeat_age']}"
            )

        print()

    with connect_repository() as conn:
        recovered_tasks = recover_stale_tasks(conn)
        

    if recovered_tasks:
        for task in recovered_tasks:
            if task["status"] == "RETRY_EXHAUSTED":
                print(
                    f"Task {task['task_id']} "
                    f"-> RETRY_EXHAUSTED "
                    f"(retry {task['retry_count']})"
                )
            else:
                print(
                    f"Task {task['task_id']} "
                    f"-> returned to WAITING "
                    f"(retry {task['retry_count']})"
                )

        print()

    while True:

        with connect_repository() as conn:
            tasks = claim_tasks(
                conn,
                worker_id=worker_id,
                limit=max_workers
            )

        if not tasks:
            print("No eligible tasks found.")
            break

        print(f"{len(tasks)} task(s) claimed.")
        print()

        with ThreadPoolExecutor(
            max_workers=max_workers
        ) as executor:

            futures = {
                executor.submit(
                    process_task,
                    task
                ): task
                for task in tasks
            }

            for future in as_completed(futures):
                task = futures[future]

                try:
                    future.result()

                except Exception as exc:
                    print()
                    print("WORKER THREAD FAILED")
                    print("--------------------")
                    print(
                        f"Task ID : "
                        f"{task['task_id']}"
                    )
                    print(
                        f"Target  : "
                        f"{task['target_name']}"
                    )
                    print(
                        f"Error   : "
                        f"{exc}"
                    )


if __name__ == "__main__":
    main()