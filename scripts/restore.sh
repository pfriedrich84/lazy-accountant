#!/bin/sh
set -eu
umask 077
cd "$(dirname "$0")/.."
source_dir="${1:?Aufruf: sh scripts/restore.sh BACKUPORDNER --yes-replace}"
if [ "${2:-}" != "--yes-replace" ]; then echo "Ersetzt Datenbank und Dokumentablage. --yes-replace erforderlich." >&2; exit 1; fi
(cd "$source_dir" && sha256sum -c SHA256SUMS)
python3 - "$source_dir/environment.env" <<'PY'
import sys
from pathlib import Path
def key(file):
    return next((line.split('=',1)[1] for line in Path(file).read_text().splitlines() if line.startswith('DJANGO_SECRET_KEY=')), None)
if not key('.env') or key('.env') != key(sys.argv[1]):
    raise SystemExit('DJANGO_SECRET_KEY in aktueller .env muss zum Backup passen. Vorher sicher ergänzen; noch nichts wurde ersetzt.')
PY
# On an error, leave the application offline instead of starting with half-restored data.
docker compose stop app worker >&2
docker compose up -d --wait db >&2
docker compose exec -T db sh -c 'exec pg_restore --clean --if-exists --exit-on-error --no-owner --no-privileges --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' < "$source_dir/database.dump"
docker compose run --rm --no-deps -T app python scripts/restore_files.py --yes-replace < "$source_dir/documents.tar"
docker compose run --rm --no-deps -T app python backend/manage.py migrate --noinput
docker compose run --rm --no-deps -T app python backend/manage.py prepare_security
docker compose run --rm --no-deps -T app python backend/manage.py verify_integrity --repair
# A job that was running in the backed-up process cannot still own a live lease.
docker compose run --rm --no-deps -T app python backend/manage.py recover_jobs
docker compose up -d --wait app worker
echo "Gemeinsame Wiederherstellung und Integritätsprüfung abgeschlossen. SMTP-Ausgänge/Orca-Anbindung gesondert prüfen."
