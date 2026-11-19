#!/bin/sh
# Consistent cold backup: stop both writers, then snapshot PostgreSQL + the entire file store.
set -eu
umask 077
cd "$(dirname "$0")/.."
destination="${1:-backups/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -m 700 -p "$destination"
if [ -e "$destination/database.dump" ]; then echo "Backup existiert bereits." >&2; exit 1; fi
restart() { docker compose up -d app worker >&2; }
trap restart EXIT
trap 'exit 1' HUP INT TERM
docker compose stop app worker >&2
docker compose run --rm --no-deps -T app python backend/manage.py verify_integrity --repair >&2
docker compose exec -T db sh -c 'exec pg_dump --format=custom --no-owner --no-privileges --username="$POSTGRES_USER" "$POSTGRES_DB"' > "$destination/database.dump"
docker compose run --rm --no-deps -T app tar -C /data -cf - . > "$destination/documents.tar"
cp .env "$destination/environment.env"
printf '%s\n' 'Lazy Accountant backup v1; PostgreSQL 18.7; database.dump + documents.tar + environment.env are one snapshot.' > "$destination/README.txt"
(cd "$destination" && sha256sum database.dump documents.tar environment.env README.txt > SHA256SUMS)
echo "Konsistente Sicherung erstellt: $destination (enthält Geheimnisse; extern verschlüsselt aufbewahren)."
