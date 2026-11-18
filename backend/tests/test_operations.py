import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "restore_files", Path(__file__).resolve().parents[2] / "scripts/restore_files.py"
)
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


def archive_bytes(name, kind=tarfile.REGTYPE):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = "/tmp/outside"
        if kind == tarfile.REGTYPE:
            member.size = 8
            archive.addfile(member, io.BytesIO(b"original"))
        else:
            archive.addfile(member)
    data.seek(0)
    return data


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../outside", tarfile.REGTYPE),
        ("/etc/passwd", tarfile.REGTYPE),
        ("link", tarfile.SYMTYPE),
        ("hardlink", tarfile.LNKTYPE),
        ("fifo", tarfile.FIFOTYPE),
    ],
)
def test_unsafe_restore_is_rejected_before_existing_data_changes(tmp_path, name, kind):
    root = tmp_path / "documents"
    root.mkdir()
    marker = root / "existing"
    marker.write_text("keep")
    with pytest.raises(ValueError):
        restore.restore_file_tree(archive_bytes(name, kind), root)
    assert marker.read_text() == "keep"


def test_safe_offline_restore_replaces_complete_tree(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "old").write_text("old")
    restore.restore_file_tree(archive_bytes("Firma/2026/10/ER/original.pdf"), root)
    assert not (root / "old").exists()
    assert (root / "Firma/2026/10/ER/original.pdf").read_bytes() == b"original"
