"""Shared technical logging for Keystone components (ADR-0014).

Two layers:

- Every record goes to the console (message only, as before) and to a rotating
  log file per component (with timestamp, level and logger). The file works
  even when the repository database is unreachable.
- Significant records (WARNING and above, or records explicitly marked as
  events) are also written to keystone.event_log so they can be queried and
  later shown in the user interface.

The repository handler uses its own autocommit connection. An event is
therefore never rolled back together with the failed work it describes (the
reason assessment runs used to disappear). If the repository cannot be
written, the handler drops that copy silently and retries with a fresh
connection next time; the file still has the record and the application keeps
running.

Business events (collector runs, assessment runs and results, findings) are
not logged here; they live in their own tables.

Usage:

    from repository.common.logging_config import configure_logging, get_logger

    configure_logging("assessment_engine", connect=connect_repository)
    logger = get_logger("assessment_engine")
    logger.warning("Rule failed", extra={"context": {"rule_key": "PG-TRAN-001"}})
    logger.info("Worker started", extra={"keystone_event": True})
"""

import json
import logging
import logging.handlers
import os
import socket
import sys
from datetime import datetime, timezone


ROOT_LOGGER_NAME = "keystone"

DEFAULT_LOG_DIR = "logs"
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
LOG_FILE_BACKUP_COUNT = 5

FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(process)d] %(message)s"
CONSOLE_FORMAT = "%(message)s"


def get_logger(name):
    """Return a logger below the shared 'keystone' root logger."""
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


class RepositoryEventHandler(logging.Handler):
    """Write significant log records to keystone.event_log.

    A record is significant when its level is at least `threshold` or when it
    was logged with extra={"keystone_event": True} (for example component
    start and stop). Optional structured identifiers can be passed as
    extra={"context": {...}} and are stored as JSONB.
    """

    def __init__(self, component, connect, threshold=logging.WARNING):
        super().__init__(level=logging.NOTSET)
        self.component = component
        self._connect = connect
        self.threshold = threshold
        self._conn = None
        self._hostname = socket.gethostname()
        self._failure_reported = False

    def is_significant(self, record):
        return (
            record.levelno >= self.threshold
            or getattr(record, "keystone_event", False)
        )

    def _connection(self):
        if self._conn is None or self._conn.closed:
            conn = self._connect()
            conn.autocommit = True
            self._conn = conn
        return self._conn

    def _discard_connection(self):
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def emit(self, record):
        if not self.is_significant(record):
            return

        try:
            exception = None
            if record.exc_info:
                exception = logging.Formatter().formatException(record.exc_info)

            context = getattr(record, "context", None)

            self._connection().execute(
                """
                INSERT INTO keystone.event_log
                (
                    logged_at, level, component, logger_name, message,
                    exception, context, hostname, process_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    datetime.fromtimestamp(record.created, timezone.utc),
                    record.levelname,
                    self.component,
                    record.name,
                    record.getMessage(),
                    exception,
                    json.dumps(context, default=str) if context else None,
                    self._hostname,
                    record.process,
                ),
            )
        except Exception as exc:
            # Logging must never break the application. The file handler has
            # the record; retry with a fresh connection on the next event.
            self._discard_connection()
            if not self._failure_reported:
                self._failure_reported = True
                print(
                    f"WARNING: could not write to keystone.event_log "
                    f"({type(exc).__name__}: {exc}); continuing with file "
                    "logging only.",
                    file=sys.stderr,
                )

    def close(self):
        self._discard_connection()
        super().close()


def shutdown_logging():
    """Close and remove all handlers of the 'keystone' root logger."""
    root = logging.getLogger(ROOT_LOGGER_NAME)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()


def configure_logging(
    component,
    connect=None,
    log_dir=None,
    level=logging.INFO,
    console=True,
):
    """Configure the shared 'keystone' logger for one component.

    component -- name used for the log file and event_log.component
    connect   -- callable returning a repository connection; enables
                 event_log. Without it only console and file are used.
    log_dir   -- directory for log files; default KEYSTONE_LOG_DIR or ./logs

    Calling it again replaces the previous configuration.
    """
    shutdown_logging()

    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(level)
    root.propagate = False

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        root.addHandler(console_handler)

    log_dir = log_dir or os.getenv("KEYSTONE_LOG_DIR", DEFAULT_LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, f"{component}.log"),
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
    root.addHandler(file_handler)

    if connect is not None:
        root.addHandler(RepositoryEventHandler(component, connect))

    return root
