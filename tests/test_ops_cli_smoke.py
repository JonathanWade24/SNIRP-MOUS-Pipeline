from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ops_help_smoke() -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "mous_pipeline.cli", "ops", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "{ui,run,status,monitor}" in proc.stdout
    assert "run" in proc.stdout
