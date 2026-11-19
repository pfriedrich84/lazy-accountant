#!/bin/sh
set -eu
# VERSION reports the signatures actually loaded by clamd, not a downloaded file.
version=$(printf 'zVERSION\000' | nc -w 5 127.0.0.1 3310 | tr -d '\000')
case "$version" in ClamAV\ */[0-9]*/*) ;; *) exit 1 ;; esac
stamp=${version##*/}
built=$(date -u -D '%a %b %d %H:%M:%S %Y' -d "$stamp" +%s)
now=$(date -u +%s)
age=$((now - built))
[ "$age" -ge -3600 ] && [ "$age" -le "${CLAMAV_MAX_SIGNATURE_AGE:-172800}" ] || exit 1
answer=$(printf 'zINSTREAM\000\000\000\000\004safe\000\000\000\000' | nc -w 5 127.0.0.1 3310 | tr -d '\000')
[ "$answer" = 'stream: OK' ]
