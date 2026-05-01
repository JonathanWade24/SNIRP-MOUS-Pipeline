from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env(fake_bin: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
    }


def _write_fake_repocli(fake_bin: Path) -> None:
    script = fake_bin / "repocli"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "case \"${1:-}\" in\n"
        "  ls)\n"
        "    printf 'drwx sub-A2002\\n'\n"
        "    printf 'drwx sub-not-a-subject\\n'\n"
        "    ;;\n"
        "  get)\n"
        "    remote=\"${2:-}\"\n"
        "    dest=\"${3:-}\"\n"
        "    case \"$remote\" in\n"
        "      */sub-A2002) mkdir -p \"$dest/sub-A2002\" ;;\n"
        "      *) echo \"not found: $remote\" >&2; exit 7 ;;\n"
        "    esac\n"
        "    ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)


def test_fetch_rdr_all_remote_writes_manifest_and_skips_invalid_listing(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_repocli(fake_bin)
    manifest = tmp_path / "manifest.json"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mous_pipeline.cli",
            "fetch-rdr",
            "--collection-path",
            "dccn/example",
            "--all-remote-subjects",
            "--manifest-out",
            str(manifest),
        ],
        cwd=PROJECT_ROOT,
        env=_env(fake_bin),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "repocli get dccn/example/sub-A2002" in proc.stdout
    assert '"A2002"' in manifest.read_text()
    assert "not-a-subject" not in manifest.read_text()


def test_fetch_rdr_execute_skip_invalid_continues_after_failed_subject(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_repocli(fake_bin)
    dest = tmp_path / "data"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mous_pipeline.cli",
            "fetch-rdr",
            "--collection-path",
            "dccn/example",
            "--subjects",
            "A2002,A9999",
            "--dest",
            str(dest),
            "--execute",
            "--skip-invalid",
        ],
        cwd=PROJECT_ROOT,
        env=_env(fake_bin),
        text=True,
        capture_output=True,
        check=True,
    )

    assert (dest / "sub-A2002").is_dir()
    assert not (dest / "sub-A9999").exists()
    assert "Downloaded 1 subject(s): A2002" in proc.stdout
    assert "Skipping sub-A9999" in proc.stderr
