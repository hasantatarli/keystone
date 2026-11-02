# PostgreSQL 17 with an SSH server, so the lab servers behave like VMs for PG_HOST_SNAPSHOT.
FROM postgres:17
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-server \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /run/sshd
COPY with-sshd.sh /usr/local/bin/with-sshd.sh
RUN chmod 755 /usr/local/bin/with-sshd.sh
