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
# Pseudo filesystems (size 0) are skipped by the parser. DATA_PATHS: where
# pg_wal of each running data directory points (sudo -n when allowed).
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

# DATA_PATHS: per postmaster (-D in its command line) the data directory, the
# real location of its pg_wal and how it was read: DIRECT, SUDO (sudo -n as
# the postmaster's user, only if a sudoers rule allows exactly this readlink),
# or DENIED. Nothing is changed; no password is ever asked.
echo "===DATA_PATHS==="
ps -eo uid=,args= 2>/dev/null |
awk '{ n = split($2, p, "/"); if (p[n] != "postgres" && p[n] != "postmaster") next
       for (i = 3; i < NF; i++) if ($i == "-D") print $1, $(i + 1) }' | sort -u |
while read -r uid data; do
    data=${data%/}
    owner=$(getent passwd "$uid" 2>/dev/null | cut -d: -f1)
    if [ -x "$data" ] && wal=$(readlink -f "$data/pg_wal" 2>/dev/null) && [ -n "$wal" ]; then
        via=DIRECT
    elif [ -n "$owner" ] && wal=$(sudo -n -u "$owner" readlink -f "$data/pg_wal" 2>/dev/null) && [ -n "$wal" ]; then
        via=SUDO
    else
        wal=""; via=DENIED
    fi
    printf '%s\t%s\t%s\n' "$data" "$wal" "$via"
done

echo "===VIRTUALIZATION==="
systemd-detect-virt --vm 2>/dev/null || true
