#!/usr/bin/env python3
"""Offline restore helper, called inside the app container by restore.sh."""
import shutil
import sys
import tarfile
from pathlib import Path

root = Path("/data")
if sys.argv[1:] != ["--yes-replace"] or not root.is_dir() or root.is_symlink():
    raise SystemExit("Explizites --yes-replace und sicherer /data-Mount erforderlich.")
# Validate every member before replacing the current file tree. Keep the incoming
# archive outside /data, so it cannot be removed as part of the replacement.
with open("/tmp/restore-documents.tar", "wb") as output:
    shutil.copyfileobj(sys.stdin.buffer, output)
with tarfile.open("/tmp/restore-documents.tar") as archive:
    for member in archive.getmembers():
        target = (root / member.name).resolve()
        if not target.is_relative_to(root) or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            raise SystemExit("Unsicherer Archiveintrag; Wiederherstellung abgebrochen.")
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    archive.extractall(root, filter="data")
Path("/tmp/restore-documents.tar").unlink()
print("Dateiablage offline wiederhergestellt.")
