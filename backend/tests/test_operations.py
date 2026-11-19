import importlib.util
import io
import subprocess
import sys
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


def test_init_env_creates_only_private_config_without_host_storage(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    script = tmp_path / "scripts/init-env.py"
    script.parent.mkdir()
    script.write_bytes((repository / "scripts/init-env.py").read_bytes())
    (tmp_path / ".env.example").write_bytes((repository / ".env.example").read_bytes())
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    environment = tmp_path / ".env"
    contents = environment.read_text()
    values = dict(line.split("=", 1) for line in contents.splitlines() if line and not line.startswith("#"))
    secrets = [values[key] for key in ("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "ADMIN_PASSWORD")]
    assert len(set(secrets)) == 3
    assert all(len(secret) >= 40 and secret not in result.stdout + result.stderr for secret in secrets)
    assert "replace-with-" not in contents
    assert environment.stat().st_mode & 0o777 == 0o600
    assert values["HTTP_BIND"] == "0.0.0.0"
    assert values["HTTP_PORT"] == "8000"
    assert not {"DOCUMENTS_ROOT", "APP_UID", "APP_GID"} & values.keys()
    assert not (tmp_path / "var").exists()
    repeated = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert repeated.returncode != 0
    assert environment.read_text() == contents
