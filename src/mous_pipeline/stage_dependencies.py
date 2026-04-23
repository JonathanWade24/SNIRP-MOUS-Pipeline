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


def parallel_execution_fronts(selected: list[str] | None = None) -> list[list[str]]:
    """Greedy topological layers: stages in the same inner list may run concurrently (DAG only).

    Order within a front follows ``STAGE_ORDER``. The runner today executes
    ``STAGE_ORDER`` serially and shares in-memory MNE objects, so overlapping
    stages in one process still requires a refactor or multi-process design.
    """
    order = selected if selected is not None else list(STAGE_ORDER)
    selected_set = set(order)
    if not order:
        return []
    errs = list_missing_stage_dependencies(order)
    if errs:
        raise ValueError("Invalid stage selection: " + "; ".join(errs))
    index = {s: i for i, s in enumerate(STAGE_ORDER)}
    completed: set[str] = set()
    fronts: list[list[str]] = []
    while len(completed) < len(selected_set):
        ready: list[str] = []
        for s in order:
            if s not in selected_set or s in completed:
                continue
            deps = STAGE_DEPENDENCIES.get(s, set())
            if not deps.issubset(completed):
                continue
            ready.append(s)
        if not ready:
            raise RuntimeError(
                "parallel_execution_fronts: cannot advance (cycle or missing deps); "
                f"remaining={sorted(selected_set - completed)}"
            )
        ready.sort(key=lambda x: index.get(x, 999))
        fronts.append(ready)
        completed.update(ready)
    return fronts
