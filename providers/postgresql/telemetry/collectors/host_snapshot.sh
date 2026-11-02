#!/bin/sh

# =============================================================================
# Key        : PG_HOST_SNAPSHOT
# Name       : Host Snapshot
# Component  : PostgreSQL.Telemetry
# Applies To : PostgreSQL
# Execution Scope : NODE
# Execution Type  : SSH
#
# Description
# -----------
# Collects minimum Linux host evidence required for PostgreSQL health
# assessment, including operating system identity, uptime, CPU, memory,
# swap and persistent filesystem capacity.
# df -a lists every mount: without it df keeps one mount per device, so the
# data directory's own mount can be hidden behind "/" (bind mounts, containers).
# Pseudo filesystems (size 0) are skipped by the parser.
# =============================================================================

echo "===HOSTNAME==="
hostname

echo "===OS_RELEASE==="
cat /etc/os-release

echo "===UPTIME==="
cat /proc/uptime

echo "===CPU==="
nproc

echo "===MEMORY==="
cat /proc/meminfo

echo "===FILESYSTEMS==="
df -a -B1 -P -x tmpfs -x devtmpfs