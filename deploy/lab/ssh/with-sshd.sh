#!/bin/bash
# Starts sshd for the HOST collector, then the container's real command.
# User "keystone" logs in with HOST_SSH_PASSWORD; it needs no privileges (reads /proc and df).
set -euo pipefail
id keystone >/dev/null 2>&1 || useradd -m -s /bin/bash keystone
echo "keystone:${HOST_SSH_PASSWORD}" | chpasswd
ssh-keygen -A >/dev/null           # host keys, if the image has none
/usr/sbin/sshd
exec "$@"
