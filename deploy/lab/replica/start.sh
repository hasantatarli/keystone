#!/bin/bash
# Streaming replica of pg17-primary: clone it once, then run as a standby.
set -euo pipefail
PGDATA=/var/lib/postgresql/data

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  until pg_isready -h "$PRIMARY_HOST" -p 5432 -q; do sleep 2; done
  chown postgres:postgres "$PGDATA"
  chmod 700 "$PGDATA"
  su postgres -c "PGPASSWORD='$REPLICATOR_PASSWORD' pg_basebackup -h '$PRIMARY_HOST' -U replicator \
    -D '$PGDATA' -R -X stream -c fast"
fi
exec su postgres -c "postgres -D '$PGDATA' -c shared_buffers=64MB -c max_connections=50 -c hot_standby=on"
