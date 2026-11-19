#!/usr/bin/env python3
"""Create local-only credentials without printing them or overwriting existing data."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
file = root / ".env"
if file.exists():
    raise SystemExit(".env existiert bereits; wird nicht überschrieben.")
content = (root / ".env.example").read_text()
for placeholder in (
    "replace-with-a-random-secret",
    "replace-with-a-random-database-password",
    "replace-with-a-password-of-at-least-12-characters",
):
    content = content.replace(placeholder, secrets.token_urlsafe(40))
fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(content)
print(
    "Private .env angelegt. Docker erstellt das Dokumentvolume beim Start. "
    "ADMIN_PASSWORD lokal in .env nachlesen; keine Geheimnisse wurden ausgegeben."
)
