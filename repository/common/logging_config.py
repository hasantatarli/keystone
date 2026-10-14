"""Shared logging (ADR-0014): console + rotating file, WARNING+ also to event_log.

Usage: configure_logging("worker", connect=...); get_logger("worker").warning(...)
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
    """Writes WARNING+ (or extra={"keystone_event": True}) to keystone.event_log.

    Own autocommit connection, so events survive the caller's rollback.
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
            # Never break the app: the file has the record; reconnect next time.
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
    """Set up console, logs/<component>.log and (if connect given) event_log.

    Safe to call again; replaces the previous setup.
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
