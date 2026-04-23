"""Shared stage order/dependency definitions and validators."""

from __future__ import annotations

STAGE_ORDER = ["m1", "m2", "m3", "m4", "m4_trial", "m5", "m6a", "m6_extra", "m10", "m11", "m12", "m7", "m8", "m9"]

STAGE_DEPENDENCIES: dict[str, set[str]] = {
    "m2": {"m1"},
    "m3": {"m2"},
    "m4": {"m3"},
    "m4_trial": {"m3"},
    "m5": {"m3"},
    "m6a": {"m3"},
    "m6_extra": {"m4"},
    "m7": {"m6a"},
    "m8": {"m7"},
    "m9": {"m7"},
    "m10": {"m4_trial"},
    "m11": {"m10"},
    "m12": {"m6a"},
}


def list_missing_stage_dependencies(selected: list[str]) -> list[str]:
    """Return human-readable dependency errors for selected stages."""
    selected_set = set(selected)
    errors: list[str] = []
    for stage in selected:
        missing = sorted(dep for dep in STAGE_DEPENDENCIES.get(stage, set()) if dep not in selected_set)
        if missing:
            errors.append(f"{stage} requires {', '.join(missing)}")
    return errors
