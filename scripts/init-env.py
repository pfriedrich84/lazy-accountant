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
uid, gid = os.getuid() or 1000, os.getgid() or 1000
content = content.replace("APP_UID=1000", f"APP_UID={uid}").replace("APP_GID=1000", f"APP_GID={gid}")
fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(content)
documents = root / "var/documents"
documents.mkdir(parents=True, exist_ok=True, mode=0o700)
if os.getuid() == 0:
    os.chown(documents, uid, gid)
print(
    "Private .env und Ablageordner angelegt. ADMIN_PASSWORD lokal in .env nachlesen; keine Geheimnisse wurden ausgegeben."
)
