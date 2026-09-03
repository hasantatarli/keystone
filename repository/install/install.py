from pathlib import Path
import re
import sys
import hashlib
import psycopg
import time


# -----------------------------------------------------------------------------
# Configuration - temporary for V1 development
# -----------------------------------------------------------------------------

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "keystone_lab",
    "user": "postgres",
    "password": "3746"
}


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

INSTALL_DIR = Path(__file__).resolve().parent
REPOSITORY_DIR = INSTALL_DIR.parent

BOOTSTRAP_FILE = INSTALL_DIR / "bootstrap.sql"
MIGRATION_SOURCES = [
    {
        "component": "Repository.Core",
        "path": REPOSITORY_DIR / "migrations" / "core",
        "prefix": "V"
    },
    {
        "component": "PostgreSQL.Telemetry",
        "path": REPOSITORY_DIR.parent
        / "providers"
        / "postgresql"
        / "telemetry"
        / "repository"
        / "migrations",
        "prefix": "PG"
    }
]

POSTGRESQL_COLLECTORS_DIR = (
    REPOSITORY_DIR.parent
    / "providers"
    / "postgresql"
    / "telemetry"
    / "collectors"
)


# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------

def connect_repository():
    return psycopg.connect(**DB_CONFIG)


def run_bootstrap(conn):
    print("Running repository bootstrap...")

    sql = BOOTSTRAP_FILE.read_text(encoding="utf-8")

    with conn.cursor() as cur:
        cur.execute(sql)

    conn.commit()

    print("Bootstrap completed.")


# -----------------------------------------------------------------------------
# Migration History
# -----------------------------------------------------------------------------

def get_successful_migrations(conn):
    sql = """
        SELECT component,
               migration_no,
               version,
               file_name,
               checksum
        FROM keystone.migration_history
        WHERE status = 'SUCCESS';
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    return rows


# -----------------------------------------------------------------------------
# Migration Discovery
# -----------------------------------------------------------------------------

def build_migration_pattern(prefix):
    return re.compile(
        rf"^{re.escape(prefix)}(?P<number>\d+)__(?P<name>.+)\.sql$",
        re.IGNORECASE
    )

def calculate_checksum(file_path):
    sha256 = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest()

def parse_metadata(file_path):
    content = file_path.read_text(encoding="utf-8")

    def get_value(field_name):
        pattern = rf"^{re.escape(field_name)}\s*:\s*(.+)$"
        match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)

        if not match:
            raise RuntimeError(
                f"Required metadata field '{field_name}' "
                f"not found in {file_path.name}"
            )

        return match.group(1).strip()

    migration_no = get_value("Migration No")
    version = get_value("Version")
    title = get_value("Title")
    author = get_value("Author")
    applies_to = get_value("Applies To")

    description_match = re.search(
        r"Description\s*\n-+\s*\n(.*?)(?=\n={5,}|\*/)",
        content,
        re.DOTALL | re.IGNORECASE
    )
    

    if not description_match:
        raise RuntimeError(
            f"Required metadata field 'Description' "
            f"not found in {file_path.name}"
        )

    description = description_match.group(1).strip()

    return {
        "migration_no": migration_no,
        "version": version,
        "title": title,
        "author": author,
        "applies_to": applies_to,
        "description": description
    }

def parse_collector_metadata(file_path):
    content = file_path.read_text(encoding="utf-8")

    def get_value(field_name):
        pattern = rf"^{re.escape(field_name)}\s*:\s*(.+)$"
        match = re.search(
            pattern,
            content,
            re.MULTILINE | re.IGNORECASE
        )

        if not match:
            raise RuntimeError(
                f"Required collector metadata field "
                f"'{field_name}' not found in {file_path.name}"
            )

        return match.group(1).strip()

    description_match = re.search(
        r"Description\s*\n-+\s*\n(.*?)(?=\n={5,}|\*/)",
        content,
        re.DOTALL | re.IGNORECASE
    )

    if not description_match:
        raise RuntimeError(
            f"Required collector metadata field "
            f"'Description' not found in {file_path.name}"
        )

    return {
        "collector_key": get_value("Key"),
        "name": get_value("Name"),
        "component": get_value("Component"),
        "applies_to": get_value("Applies To"),
        "execution_scope": get_value("Execution Scope"),
        "description": description_match.group(1).strip()
    }

def discover_collectors():
    collectors = []

    if not POSTGRESQL_COLLECTORS_DIR.exists():
        raise RuntimeError(
            f"Collector directory does not exist: "
            f"{POSTGRESQL_COLLECTORS_DIR}"
        )

    for file_path in POSTGRESQL_COLLECTORS_DIR.glob("*.sql"):

        metadata = parse_collector_metadata(file_path)

        collectors.append(
            {
                "collector_key": metadata["collector_key"],
                "component": metadata["component"],
                "name": metadata["name"],
                "execution_scope": metadata["execution_scope"],
                "script_file": str(
                    file_path.relative_to(REPOSITORY_DIR.parent)
                ).replace("\\", "/"),
                "checksum": calculate_checksum(file_path),
                "description": metadata["description"],
                "path": file_path
            }
        )

    return collectors

def discover_migrations():
    migrations = []

    for source in MIGRATION_SOURCES:
        component = source["component"]
        migration_dir = source["path"]
        prefix = source["prefix"]

        if not migration_dir.exists():
            print(
                f"WARNING: Migration directory does not exist "
                f"for {component}: {migration_dir}"
            )
            continue

        pattern = build_migration_pattern(prefix)

        for file_path in migration_dir.glob("*.sql"):

            match = pattern.match(file_path.name)

            if not match:
                print(
                    f"WARNING: Ignoring invalid migration file "
                    f"for {component}: {file_path.name}"
                )
                continue

            migration_no = int(match.group("number"))

            metadata = parse_metadata(file_path)

            expected_version = (
                f"{prefix}{migration_no:03d}"
            )

            if metadata["version"].upper() != expected_version:
                raise RuntimeError(
                    f"Version mismatch in {file_path.name}: "
                    f"file name indicates {expected_version}, "
                    f"metadata contains {metadata['version']}"
                )

            try:
                metadata_migration_no = int(
                    metadata["migration_no"]
                )
            except ValueError:
                raise RuntimeError(
                    f"Invalid Migration No in {file_path.name}: "
                    f"{metadata['migration_no']}"
                )

            if metadata_migration_no != migration_no:
                raise RuntimeError(
                    f"Migration number mismatch in {file_path.name}: "
                    f"file name indicates {migration_no}, "
                    f"metadata contains {metadata_migration_no}"
                )

            migrations.append(
                {
                    "component": component,
                    "migration_no": migration_no,
                    "version": expected_version,
                    "file_name": file_path.name,
                    "path": file_path,
                    "checksum": calculate_checksum(file_path),
                    "metadata": metadata
                }
            )

    migrations.sort(
        key=lambda x: (
            x["component"],
            x["migration_no"]
        )
    )

    return migrations



# -----------------------------------------------------------------------------
# Pending Migrations
# -----------------------------------------------------------------------------

def get_pending_migrations(discovered, successful):
    successful_keys = {
        (
            row[0],  # component
            row[1],  # migration_no
            row[2],  # version
            row[3]   # file_name
        )
        for row in successful
    }

    return [
        migration
        for migration in discovered
        if (
            migration["component"],
            migration["migration_no"],
            migration["version"],
            migration["file_name"]
        )
        not in successful_keys
    ]

def write_migration_history(
    conn,
    migration,
    status,
    execution_time_ms,
    status_message=None,
    error_message=None
):
    metadata = migration["metadata"]

    sql = """
        INSERT INTO keystone.migration_history
        (
            component,
            migration_no,
            version,
            file_name,
            description,
            checksum,
            status,
            executed_by,
            execution_time_ms,
            status_message,
            error_message
        )
        VALUES
        (
            %(component)s,
            %(migration_no)s,
            %(version)s,
            %(file_name)s,
            %(description)s,
            %(checksum)s,
            %(status)s,
            %(executed_by)s,
            %(execution_time_ms)s,
            %(status_message)s,
            %(error_message)s
        );
    """

    params = {
        "component": migration["component"],
        "migration_no": migration["migration_no"],
        "version": migration["version"],
        "file_name": migration["file_name"],
        "description": metadata["description"],
        "checksum": migration["checksum"],
        "status": status,
        "executed_by": "keystone-installer",
        "execution_time_ms": execution_time_ms,
        "status_message": status_message,
        "error_message": error_message
    }

    with conn.cursor() as cur:
        cur.execute(sql, params)

    #conn.commit()

def execute_migration(conn, migration):
    print()
    print(
        f"Executing {migration['version']} "
        f"- {migration['file_name']}"
    )

    sql = migration["path"].read_text(encoding="utf-8")

    start_time = time.perf_counter()

    try:
        with conn.cursor() as cur:
            cur.execute(sql)

        #conn.commit()

        execution_time_ms = int(
            (time.perf_counter() - start_time) * 1000
        )

        write_migration_history(
            conn=conn,
            migration=migration,
            status="SUCCESS",
            execution_time_ms=execution_time_ms,
            status_message="Migration completed successfully."
        )

        conn.commit()

        update_current_migration(conn, migration)

        print(
            f"SUCCESS - {migration['version']} "
            f"({execution_time_ms} ms)"
        )

        return True

    except Exception as exc:
        conn.rollback()

        execution_time_ms = int(
            (time.perf_counter() - start_time) * 1000
        )

        write_migration_history(
            conn=conn,
            migration=migration,
            status="FAILED",
            execution_time_ms=execution_time_ms,
            status_message="Migration execution failed.",
            error_message=str(exc)
        )

        conn.commit()

        print(
            f"FAILED - {migration['version']} "
            f"({execution_time_ms} ms)"
        )
        print(str(exc))

        return False

def update_current_migration(conn, migration):
    component = migration["component"]

    control_name = f"{component}.CurrentMigration"

    sql = """
        INSERT INTO keystone.control
        (
            name,
            value,
            value_type,
            namespace,
            description,
            updated_by
        )
        VALUES
        (
            %(name)s,
            %(version)s,
            'VERSION',
            %(namespace)s,
            %(description)s,
            'keystone-installer'
        )
        ON CONFLICT (name)
        DO UPDATE SET
            value       = EXCLUDED.value,
            value_type  = EXCLUDED.value_type,
            namespace   = EXCLUDED.namespace,
            description = EXCLUDED.description,
            updated_at  = clock_timestamp(),
            updated_by  = EXCLUDED.updated_by;
    """

    params = {
        "name": control_name,
        "version": migration["version"],
        "namespace": component,
        "description": (
            f"Latest successfully applied migration for {component}"
        )
    }

    with conn.cursor() as cur:
        cur.execute(sql, params)

    conn.commit()   

# -----------------------------------------------------------------------------
# Collector Registration
# -----------------------------------------------------------------------------
def register_collectors(conn):
    collectors = discover_collectors()

    sql = """
        INSERT INTO keystone.collector_definition
        (
            collector_key,
            component,
            name,
            script_file,
            checksum,
            execution_scope,
            is_active,
            description
        )
        VALUES
        (
            %(collector_key)s,
            %(component)s,
            %(name)s,
            %(script_file)s,
            %(checksum)s,
            %(execution_scope)s,
            TRUE,
            %(description)s
        )
        ON CONFLICT (collector_key)
        DO UPDATE SET
            component   = EXCLUDED.component,
            name        = EXCLUDED.name,
            script_file = EXCLUDED.script_file,
            checksum    = EXCLUDED.checksum,
            execution_scope = EXCLUDED.execution_scope,
            is_active   = TRUE,
            description = EXCLUDED.description;
    """

    print()
    print("Registering collectors...")

    with conn.cursor() as cur:

        for collector in collectors:

            cur.execute(sql, collector)

            print(
                f"  {collector['collector_key']} "
                f"- {collector['component']} "
                f"- {collector['name']}"
            )
            print(
                f"    Checksum: {collector['checksum']}"
            )

    conn.commit()

    print(
        f"Collector registration completed. "
        f"{len(collectors)} collector(s) registered."
    )  
# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():

    print()
    print("Keystone Repository Installer")
    print("=============================")
    print()

    try:

        with connect_repository() as conn:

            print("Connected to Keystone repository.")
            print()

            run_bootstrap(conn)

            print()

            successful = get_successful_migrations(conn)
            discovered = discover_migrations()

            pending = get_pending_migrations(
                discovered,
                successful
            )

            print()
            print(f"Discovered migrations : {len(discovered)}")
            print(f"Successful migrations : {len(successful)}")
            print(f"Pending migrations    : {len(pending)}")
            print()

            if pending:

                print("Pending migrations:")

                for migration in pending:
                    metadata = migration["metadata"]

                    print()
                    print(
                        f"  [{migration['component']}] "
                        f"{migration['version']} "
                        f"- {migration['file_name']}"
                    )
                    print(f"    Title      : {metadata['title']}")
                    print(f"    Author     : {metadata['author']}")
                    print(f"    Applies To : {metadata['applies_to']}")
                    print(f"    Checksum   : {migration['checksum']}")
                    print()
                    print("Executing pending migrations...")

                    for migration in pending:
                        success = execute_migration(conn, migration)

                        if not success:
                            print()
                            print(
                                "Migration chain stopped because "
                                f"{migration['version']} failed."
                            )

                            sys.exit(1)

            else:
                print("No pending migrations.")

            register_collectors(conn)

        print()
        print("Installer completed successfully.")

    except Exception as exc:

        print()
        print("ERROR")
        print("-----")
        print(str(exc))

        sys.exit(1)


if __name__ == "__main__":
    main()