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

echo "===CAPTURED_AT==="
date -u +%Y-%m-%dT%H:%M:%SZ

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

# BLOCK_DEVICES: lsblk ROTA per /dev device (1 rotating, 0 not); VIRTUALIZATION:
# the hypervisor or "none". Virtual disks often report 1 on SSD: a note only.
echo "===BLOCK_DEVICES==="
df -a -P -x tmpfs -x devtmpfs | awk 'NR > 1 && $1 ~ /^\/dev\// {print $1}' | sort -u |
while read -r device; do
    echo "$device $(lsblk -ndo ROTA "$device" 2>/dev/null)"
done

echo "===VIRTUALIZATION==="
systemd-detect-virt --vm 2>/dev/null || true
