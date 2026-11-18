#!/usr/bin/env python3
"""Offline restore helper. Validate the complete archive before replacing files."""

import shutil
import sys
import tarfile
import tempfile
from pathlib import Path


def restore_file_tree(source, root: Path):
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Sicherer bestehender Ablageordner erforderlich.")
    root = root.resolve()
    # Keep the incoming archive outside the tree being replaced. It may be large;
    # spool to disk, not to application memory. TemporaryFile is removed on error.
    with tempfile.TemporaryFile() as incoming:
        shutil.copyfileobj(source, incoming)
        incoming.seek(0)
        with tarfile.open(fileobj=incoming) as archive:
            for member in archive.getmembers():
                target = (root / member.name).resolve()
                if (
                    not target.is_relative_to(root)
                    or member.issym()
                    or member.islnk()
                    or not (member.isfile() or member.isdir())
                ):
                    raise ValueError("Unsicherer Archiveintrag; Wiederherstellung abgebrochen.")
            for child in root.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            archive.extractall(root, filter="data")


def main():
    if sys.argv[1:] != ["--yes-replace"]:
        raise SystemExit("Explizites --yes-replace erforderlich.")
    restore_file_tree(sys.stdin.buffer, Path("/data"))
    print("Dateiablage offline wiederhergestellt.")


if __name__ == "__main__":
    main()
