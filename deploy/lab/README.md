# Multi-system lab

Five PostgreSQL servers in Docker on one VM (`pg-lab-docker`, 192.168.1.104), next to the Patroni lab, to verify Keystone on more than one system (DEVELOPMENT_STATUS, 2026-10-30).

| Container | Port | Shape | Why |
| --- | --- | --- | --- |
| `pg15-standalone` | 5415 | single server | oldest supported version, no cluster |
| `pg16-standalone` | 5416 | single server | version differences |
| `pg18-standalone` | 5418 | single server | newest version (asynchronous I/O settings) |
| `pg17-primary` / `pg17-replica` | 5417 / 5427 | primary and streaming replica (no Patroni) | a second cluster |

Every primary and standalone server has `keystone_monitor` (`pg_monitor`, SELECT on sequences) and the databases `app` and `datawiser_tests`; the same names on every system check that Keystone keeps targets apart. The replica copies the primary.

## Start

```bash
cd deploy/lab
cp .env.example .env        # set the three passwords
docker compose up -d
docker compose ps           # all five "running"
```

The init scripts run only on an empty data volume. To start over: `docker compose down -v`.

## Check

```bash
psql -h 192.168.1.104 -p 5427 -U keystone_monitor -d postgres -c "select pg_is_in_recovery()"   # t (replica)
psql -h 192.168.1.104 -p 5417 -U keystone_monitor -d postgres -c "select client_addr, state from pg_stat_replication"
```

The lab is for testing only: every server accepts password connections from anywhere (official image default).
