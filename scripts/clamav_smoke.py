#!/usr/bin/env python3
"""Run inside app container: genuine INSTREAM smoke, no persistent EICAR file."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from accounting import scanner  # noqa: E402


def main():
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    harmless = scanner.scan(b"Harmless ClamAV Compose smoke")
    assert harmless.result == "clean", harmless
    engine = harmless.engine
    verdict = scanner.scan(eicar)
    assert verdict.result == "infected", verdict
    print(f"ClamAV INSTREAM ready: {engine}; harmless EICAR detected: {verdict.signature}")


if __name__ == "__main__":
    main()
