#!/bin/sh
# =============================================================================
# Keystone offline evidence collector (Linux / macOS)
#
# Runs the read-only Keystone scripts on one or more PostgreSQL servers with
# psql: the node script once per server, the database script in every
# database it finds, and the host script when run on the server itself.
# Everything goes into one archive to send. The password is asked, never
# written to disk, and removed from the environment at the end.
#
#   sh keystone_collect.sh
# =============================================================================

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
STAMP=$(date +%Y%m%d-%H%M%S)

ask() { printf "%s" "$1" >&2; read -r answer; [ -n "$answer" ] && echo "$answer" || echo "$2"; }

PSQL=$(command -v psql 2>/dev/null || true)
if [ -z "$PSQL" ]; then
    for p in /usr/lib/postgresql/*/bin/psql /usr/pgsql-*/bin/psql /opt/homebrew/bin/psql; do
        [ -x "$p" ] && PSQL=$p
    done
fi
[ -z "$PSQL" ] && PSQL=$(ask "psql bulunamadi. Tam yolu: " "")
[ -x "$PSQL" ] || { echo "psql calistirilamiyor: $PSQL" >&2; exit 1; }

echo "Keystone offline kanit toplama (salt okunur)"
HOSTS=$(ask "Sunucu(lar), virgulle (bu makinedeki sunucu icin: local) [local]: " "local")
PORT=$(ask "Port [5432]: " "5432")
PGUSER_IN=$(ask "Kullanici [postgres]: " "postgres")
printf "Sifre (yerel peer baglantisinda bos birakin): " >&2
stty -echo 2>/dev/null; read -r PGPASSWORD; stty echo 2>/dev/null; echo >&2
OUT=$(ask "Cikti klasoru [$HERE/keystone_evidence_$STAMP]: " "$HERE/keystone_evidence_$STAMP")
mkdir -p "$OUT"

export PGPASSWORD PGCLIENTENCODING=UTF8 PGCONNECT_TIMEOUT=10
trap 'unset PGPASSWORD' EXIT

safe() { echo "$1" | sed 's/[^A-Za-z0-9._-]/_/g'; }

for HOST in $(echo "$HOSTS" | tr ',' ' '); do
    # Files are named after the server as typed (this machine's name for local); Keystone matches them.
    if [ "$HOST" = "local" ] || [ "$HOST" = "localhost" ]; then LABEL=$(hostname); else LABEL=$HOST; fi
    NAME=$(safe "$LABEL")
    if [ "$HOST" = "local" ]; then CONN="-p $PORT -U $PGUSER_IN"; else CONN="-h $HOST -p $PORT -U $PGUSER_IN"; fi

    echo "[$LABEL] node script..."
    # shellcheck disable=SC2086
    if ! "$PSQL" -X -q -At -v ON_ERROR_STOP=1 $CONN -d postgres -f "$HERE/keystone_node.sql" \
            -o "$OUT/${NAME}_node.json"; then
        echo "[$LABEL] baglanilamadi ya da script hata verdi; bu sunucu atlandi." >&2
        rm -f "$OUT/${NAME}_node.json"
        continue
    fi

    # shellcheck disable=SC2086
    "$PSQL" -X -q -At -v ON_ERROR_STOP=1 $CONN -d postgres \
        -c "SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY 1" |
    while IFS= read -r DB; do
        [ -z "$DB" ] && continue
        echo "[$LABEL] veritabani: $DB"
        # shellcheck disable=SC2086
        "$PSQL" -X -q -At -v ON_ERROR_STOP=1 $CONN -d "$DB" -f "$HERE/keystone_database.sql" \
            -o "$OUT/${NAME}_db_$(safe "$DB").json" ||
            { echo "[$LABEL] $DB atlandi (hata)." >&2; rm -f "$OUT/${NAME}_db_$(safe "$DB").json"; }
    done

    if [ "$HOST" = "local" ] || [ "$(ask "$LABEL bu makine mi? Sunucu bilgisi de toplansin mi (e/h) [h]: " "h")" = "e" ]; then
        sh "$HERE/host_snapshot.sh" > "$OUT/${NAME}_host.txt" 2>/dev/null && echo "[$LABEL] sunucu bilgisi toplandi."
    fi
done

unset PGPASSWORD
ARCHIVE="$OUT.tar.gz"
tar -czf "$ARCHIVE" -C "$(dirname "$OUT")" "$(basename "$OUT")"
echo
echo "Tamamlandi: $ARCHIVE"
echo "Bu dosyayi gonderin. Icerigi duz metindir; gondermeden once inceleyebilirsiniz."
