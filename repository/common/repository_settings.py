"""Connection settings of the Keystone repository, in one place.

Read from KEYSTONE_REPOSITORY_* environment variables when a connection is
opened, not at import. Temporary for V1: these settings will be managed from
the web interface (Hasan, 2026-11-18).

The user has no default: Keystone never falls back to a superuser silently.
The database defaults to the product name, `keystone`.
"""

import os


DEFAULT_DATABASE = "keystone"


class RepositorySettingsError(SystemExit):
    """A required setting is missing. Ends a command with its message, no traceback."""


def repository_settings(environ=None):
    """psycopg.connect keyword arguments for the repository."""
    env = os.environ if environ is None else environ
    user = (env.get("KEYSTONE_REPOSITORY_USER") or "").strip()
    if not user:
        raise RepositorySettingsError(
            "KEYSTONE_REPOSITORY_USER is not set: the user Keystone connects to its repository "
            "with. Set it with the other KEYSTONE_REPOSITORY_* variables (host, port, database, "
            "password); see the Command Reference.")
    return {
        "host": env.get("KEYSTONE_REPOSITORY_HOST") or "localhost",
        "port": int(env.get("KEYSTONE_REPOSITORY_PORT") or "5432"),
        "dbname": env.get("KEYSTONE_REPOSITORY_DB") or DEFAULT_DATABASE,
        "user": user,
        "password": env.get("KEYSTONE_REPOSITORY_PASSWORD"),
    }
