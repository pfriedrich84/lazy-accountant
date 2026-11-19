#!/bin/sh
set -eu
umask 077
if [ "$(id -u)" = "0" ]; then
  echo "App/Worker nicht als root starten. Containerbenutzer (1000:1000) und Volumerechte prüfen." >&2
  exit 1
fi
case "${1:-web}" in
  web)
    python backend/manage.py migrate --noinput
    if [ "${BOOTSTRAP_DEMO:-0}" = "1" ]; then
      python backend/manage.py bootstrap --demo
    else
      python backend/manage.py bootstrap
    fi
    exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
    ;;
  worker)
    exec python backend/manage.py qcluster
    ;;
  *) exec "$@" ;;
esac
