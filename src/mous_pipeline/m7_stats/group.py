"""Module 7 group-level inference."""

from __future__ import annotations

import statistics

import numpy as np
from scipy.stats import wilcoxon


def run_group_model(subject_metrics: list[dict], *, test: str = "wilcoxon") -> dict:
    """Run simple group-level inference across subject manifest metrics."""
    if not subject_metrics:
        raise ValueError("No subject metrics provided for group model.")

    keys = [
        "dci_zinnen",
        "dci_woorden",
        "dci_rest",
        "p_task_vs_rest",
        "p_zinnen_vs_woorden",
        "p_woorden_vs_rest",
    ]
    out: dict[str, dict] = {}
    for key in keys:
        vals = [float(m[key]) for m in subject_metrics if key in m and m[key] is not None]
        if not vals:
            continue
        arr = np.asarray(vals, dtype=float)
        stat = {
            "n": int(arr.size),
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "std": float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0,
        }
        if test == "wilcoxon" and arr.size > 1:
            w = wilcoxon(arr - 0.0, alternative="two-sided", zero_method="wilcox")
            stat["wilcoxon_stat"] = float(w.statistic)
            stat["wilcoxon_p"] = float(w.pvalue)
        elif test == "lme":
            # Placeholder summary for LME mode without introducing extra heavy dependencies.
            stat["lme_note"] = "LME mode selected; install and integrate dedicated mixed-model package."
            stat["mean_ci95"] = [
                float(statistics.fmean(arr) - 1.96 * np.std(arr, ddof=1) / np.sqrt(arr.size))
                if arr.size > 1
                else float(arr[0]),
                float(statistics.fmean(arr) + 1.96 * np.std(arr, ddof=1) / np.sqrt(arr.size))
                if arr.size > 1
                else float(arr[0]),
            ]
        out[key] = stat
    return {
        "test": test,
        "n_subjects": len(subject_metrics),
        "metrics": out,
    }
