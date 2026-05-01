from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def events_tsv_path(repo_root: Path) -> Path:
    candidates = list(repo_root.glob("**/sub-A2002_task-auditory_events.tsv"))
    if not candidates:
        pytest.skip("No sub-A2002 events TSV found in workspace.")
    return candidates[0]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify data/script-coupled tests so quick runs can skip them."""
    for item in items:
        fixturenames = set(getattr(item, "fixturenames", ()))
        if {"repo_root", "events_tsv_path"} & fixturenames:
            item.add_marker(pytest.mark.integration)

        if "test_m3_epoching.py" in item.nodeid:
            item.add_marker(pytest.mark.slow)
