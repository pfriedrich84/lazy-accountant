#!/bin/sh
set -eu
# An idle scanner need not have fresh signatures or even a loaded database.
# Health probes must not cause updates. Every scan performs its own update gate.
exec python3 -c 'import urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open("http://127.0.0.1:3311/health", timeout=5).read()'
