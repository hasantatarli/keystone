#!/bin/bash
# Runs once when a primary or standalone server is initialised.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
-- The monitoring user Keystone connects with: pg_monitor plus SELECT on sequences (telemetry README).
CREATE ROLE keystone_monitor LOGIN PASSWORD '${KEYSTONE_MONITOR_PASSWORD}' IN ROLE pg_monitor;
CREATE ROLE replicator LOGIN REPLICATION PASSWORD '${REPLICATOR_PASSWORD}';

-- Same database names on every system: Keystone must keep targets apart.
CREATE DATABASE app;
CREATE DATABASE datawiser_tests;
SQL

# "all" in pg_hba does not cover replication connections; the replica needs its own line.
echo "host replication replicator all scram-sha-256" >> "$PGDATA/pg_hba.conf"

for db in app datawiser_tests; do
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<SQL
CREATE TABLE orders (id serial PRIMARY KEY, customer int, created timestamptz DEFAULT now());
CREATE INDEX orders_customer_idx ON orders (customer);
INSERT INTO orders (customer) SELECT g % 1000 FROM generate_series(1, 20000) g;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO keystone_monitor;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO keystone_monitor;
SQL
done
