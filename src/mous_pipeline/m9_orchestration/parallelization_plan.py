"""RAM budgeting helpers for subject-parallelism and DAG overlap (protocol deliverables)."""

from __future__ import annotations

import math
from typing import Any

from ..stage_dependencies import STAGE_ORDER, parallel_execution_fronts


def recommend_subject_parallelism(
    *,
    total_ram_gb: float,
    os_reserve_gb: float,
    peak_rss_gb: float,
    n_cpus: int = 6,
) -> dict[str, Any]:
    """Conservative cap: floor((total - reserve) / peak); optional OMP thread hint."""
    if peak_rss_gb <= 0:
        raise ValueError("peak_rss_gb must be positive")
    budget = total_ram_gb - os_reserve_gb
    if budget <= 0:
        raise ValueError("total_ram_gb must exceed os_reserve_gb")
    n_subjects = int(math.floor(budget / peak_rss_gb))
    n_subjects = max(0, n_subjects)
    omp = max(1, int(math.floor(n_cpus / n_subjects))) if n_subjects else n_cpus
    return {
        "n_subjects_max_conservative": n_subjects,
        "total_ram_gb": total_ram_gb,
        "os_reserve_gb": os_reserve_gb,
        "budget_gb": round(budget, 6),
        "peak_rss_gb": peak_rss_gb,
        "n_cpus": n_cpus,
        "suggested_omp_num_threads_per_process": omp,
        "formula": "n_subjects <= floor((total_ram_gb - os_reserve_gb) / peak_rss_gb)",
    }


def dag_parallelism_report(selected: list[str] | None = None) -> dict[str, Any]:
    fronts = parallel_execution_fronts(selected)
    max_width = max((len(f) for f in fronts), default=0)
    runner_note = (
        "run_subject executes STAGE_ORDER serially and shares epochs/raw in one process; "
        "intra-subject overlap needs subprocess workers or disk handoff — measure RSS_total."
    )
    return {
        "stages": selected if selected is not None else list(STAGE_ORDER),
        "parallel_fronts": fronts,
        "max_front_width": max_width,
        "subject_level_parallelism": "safe_to_scale_with_N_processes_if_N_times_peak_rss_fits_RAM",
        "intra_subject_overlap": runner_note,
    }


def intra_subject_pilot_protocol() -> dict[str, str]:
    """Document the two-worker spike from the RAM protocol (no automatic execution)."""
    return {
        "goal": (
            "After m3, compare peak RSS of sequential run vs running two workers "
            "(e.g. m4 in parent, m5 in child that reloads from disk)."
        ),
        "steps": (
            "1) Baseline: one subject, cold cache, --memory-profile, record peak_rss_mb. "
            "2) Experimental: fork/spawn after m3 or two terminals with disjoint --only "
            "stages only if each reloads inputs (otherwise invalid). "
            "3) Compare RSS_total (sum of process RSS from ps) to sequential peak."
        ),
        "success": "RSS_total < 32 GiB (minus OS reserve) with acceptable wall time.",
    }
