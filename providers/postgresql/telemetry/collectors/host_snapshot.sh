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
df -B1 -P -x tmpfs -x devtmpfs