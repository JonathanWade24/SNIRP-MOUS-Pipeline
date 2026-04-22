from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def pilot_artifact_dir(repo_root: Path) -> Path:
    path = repo_root / "MOUS_A2002_pilot(2)"
    if not path.exists():
        pytest.skip("Pilot artifact directory not available.")
    return path


@pytest.fixture
def events_tsv_path(repo_root: Path) -> Path:
    candidates = list(repo_root.glob("**/sub-A2002_task-auditory_events.tsv"))
    if not candidates:
        pytest.skip("No sub-A2002 events TSV found in workspace.")
    return candidates[0]
