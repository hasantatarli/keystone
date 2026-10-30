# Multi-system lab

Five PostgreSQL servers in Docker on one VM (`pg-lab-docker`, 192.168.1.104), next to the Patroni lab, to verify Keystone on more than one system (DEVELOPMENT_STATUS, 2026-10-30). Each server has its own address, all on port 5432.

| Container | Address | Shape | Why |
| --- | --- | --- | --- |
| `pg15-standalone` | 192.168.1.105 | single server | oldest supported version, no cluster |
| `pg16-standalone` | 192.168.1.106 | single server | version differences |
| `pg17-primary` / `pg17-replica` | 192.168.1.107 / .108 | primary and streaming replica (no Patroni) | a second cluster |
| `pg18-standalone` | 192.168.1.109 | single server | newest version (asynchronous I/O settings) |

The addresses are extra IPs of the VM's network card (netplan `addresses:`), and each container publishes 5432 on its own address. macvlan is not used: the VM is bridged over Wi-Fi, which drops frames from additional MAC addresses.

Every primary and standalone server has `keystone_monitor` (`pg_monitor`, SELECT on sequences) and the databases `app` and `datawiser_tests`; the same names on every system check that Keystone keeps targets apart. The replica copies the primary.

## Start

```bash
cd deploy/lab
cp .env.example .env        # set the three passwords; check the addresses
docker compose up -d
docker compose ps           # all five "running"
```

The init scripts run only on an empty data volume. To start over: `docker compose down -v`.

## Check

```bash
psql -h 192.168.1.108 -U keystone_monitor -d postgres -c "select pg_is_in_recovery()"   # t (replica)
psql -h 192.168.1.107 -U keystone_monitor -d postgres -c "select client_addr, state from pg_stat_replication"
```

## SSH (host data)

`pg17-primary` and `pg17-replica` run from a small image (`ssh/`, PostgreSQL 17 plus `openssh-server`) and accept SSH on port 2222 of their address as user `keystone` with `HOST_SSH_PASSWORD`, like two VMs. Keystone's HOST connection for each node uses that port; `PG_HOST_SNAPSHOT` then reads the container's CPU, memory and filesystems, and the data directory is the Docker volume mounted at `/var/lib/postgresql/data`. Port 22 stays the Docker host's own SSH.

```bash
docker compose up -d --build pg17-primary pg17-replica   # data volumes are kept
ssh -p 2222 keystone@192.168.1.107 df -h /var/lib/postgresql/data
```

The lab is for testing only: every server accepts password connections from anywhere (official image default).
