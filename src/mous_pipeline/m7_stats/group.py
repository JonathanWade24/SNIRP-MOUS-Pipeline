"""Module 7 group-level inference."""

from __future__ import annotations

import statistics
from collections import Counter

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon
import statsmodels.formula.api as smf


def _wilcoxon_stat(arr: np.ndarray) -> dict:
    """One-sample Wilcoxon signed-rank test against zero."""
    if arr.size < 2:
        return {}
    w = wilcoxon(arr, alternative="two-sided", zero_method="wilcox")
    return {"wilcoxon_stat": float(w.statistic), "wilcoxon_p": float(w.pvalue)}


def _scalar_summary(arr: np.ndarray, *, test: str) -> dict:
    stat: dict = {
        "n": int(arr.size),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "std": float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0,
    }
    if test == "wilcoxon":
        stat.update(_wilcoxon_stat(arr))
    elif test == "lme":
        stat["lme_note"] = "LME mode selected; install and integrate dedicated mixed-model package."
        if arr.size > 1:
            se = np.std(arr, ddof=1) / np.sqrt(arr.size)
            stat["mean_ci95"] = [float(np.mean(arr) - 1.96 * se), float(np.mean(arr) + 1.96 * se)]
        else:
            stat["mean_ci95"] = [float(arr[0]), float(arr[0])]
    return stat


def _aggregate_m11_coupling(subject_metrics: list[dict], *, test: str) -> dict:
    """Aggregate per-subject m11_coupling r values across subjects.

    For each condition×feature pair, collects the per-subject Spearman r and
    runs a one-sample Wilcoxon against r=0.  Also fits a pooled OLS with a
    subject fixed effect using all available trial tables stored in metrics
    under 'm11_pooled_trials' (list of dicts) when present.
    """
    coupling_keys = [
        "zinnen_prestim_beta_vs_mtg",
        "zinnen_n400m_vs_mtg",
        "zinnen_dci_trial_vs_mtg",
        "woorden_prestim_beta_vs_mtg",
        "woorden_n400m_vs_mtg",
        "woorden_dci_trial_vs_mtg",
    ]
    out: dict = {}

    # ── Per-key r aggregation ────────────────────────────────────────────────
    for key in coupling_keys:
        r_vals = []
        for m in subject_metrics:
            coupling = m.get("m11_coupling") or {}
            entry = coupling.get(key)
            if isinstance(entry, dict) and entry.get("r") is not None:
                r_vals.append(float(entry["r"]))
        if not r_vals:
            continue
        arr = np.asarray(r_vals, dtype=float)
        stat = _scalar_summary(arr, test=test)
        out[key] = stat

    # ── lme_like r2 aggregation ──────────────────────────────────────────────
    r2_vals = []
    for m in subject_metrics:
        coupling = m.get("m11_coupling") or {}
        lme = coupling.get("lme_like") or {}
        if lme.get("r2") is not None:
            r2_vals.append(float(lme["r2"]))
    if r2_vals:
        arr = np.asarray(r2_vals, dtype=float)
        out["lme_like_r2"] = _scalar_summary(arr, test=test)

    # ── Pooled OLS with subject fixed effect ─────────────────────────────────
    # Requires each subject manifest to carry m11_trials_rows (list[dict])
    # populated by the runner from the m10 joined CSV.
    trial_frames = []
    for i, m in enumerate(subject_metrics):
        rows = m.get("m11_trials_rows")
        if rows:
            df = pd.DataFrame(rows)
            df["subject"] = str(m.get("subject_id", i))
            trial_frames.append(df)

    if trial_frames:
        pooled = pd.concat(trial_frames, ignore_index=True)
        required = {"mtg_beta", "prestim_beta", "n400m", "dci_trial", "condition", "pos_in_block", "subject"}
        if required.issubset(pooled.columns) and len(pooled) >= 20:
            try:
                fit = smf.ols(
                    "mtg_beta ~ prestim_beta + n400m + dci_trial + C(condition) + pos_in_block + C(subject)",
                    data=pooled,
                ).fit()
                out["pooled_ols"] = {
                    "n_trials": int(len(pooled)),
                    "n_subjects": int(pooled["subject"].nunique()),
                    "r2": float(fit.rsquared),
                    "p_prestim_beta": float(fit.pvalues.get("prestim_beta", np.nan)),
                    "p_n400m": float(fit.pvalues.get("n400m", np.nan)),
                    "p_dci_trial": float(fit.pvalues.get("dci_trial", np.nan)),
                }
            except Exception as exc:
                out["pooled_ols_error"] = str(exc)

    return out


def _aggregate_m12(subject_metrics: list[dict], *, test: str) -> dict:
    """Aggregate per-subject m12 wave-validation z-scores."""
    z_vals = [
        float(m["m12_null_summary"]["z"])
        for m in subject_metrics
        if isinstance(m.get("m12_null_summary"), dict)
        and m["m12_null_summary"].get("z") is not None
    ]
    if not z_vals:
        return {}
    arr = np.asarray(z_vals, dtype=float)
    return _scalar_summary(arr, test=test)


def _pilot_verdict_counts(subject_metrics: list[dict]) -> dict:
    verdicts = [m.get("pilot_verdict") for m in subject_metrics if m.get("pilot_verdict")]
    counts = dict(Counter(verdicts))
    counts["total"] = len(subject_metrics)
    return counts


def run_group_model(subject_metrics: list[dict], *, test: str = "wilcoxon") -> dict:
    """Run group-level inference across subject manifest metrics."""
    if not subject_metrics:
        raise ValueError("No subject metrics provided for group model.")

    scalar_keys = [
        "dci_zinnen",
        "dci_woorden",
        "dci_rest",
        "p_task_vs_rest",
        "p_zinnen_vs_woorden",
        "p_woorden_vs_rest",
    ]
    out: dict[str, dict] = {}
    for key in scalar_keys:
        vals = [float(m[key]) for m in subject_metrics if key in m and m[key] is not None]
        if not vals:
            continue
        out[key] = _scalar_summary(np.asarray(vals, dtype=float), test=test)

    m11 = _aggregate_m11_coupling(subject_metrics, test=test)
    if m11:
        out["m11_coupling"] = m11

    m12 = _aggregate_m12(subject_metrics, test=test)
    if m12:
        out["m12_wave_validation_z"] = m12

    return {
        "test": test,
        "n_subjects": len(subject_metrics),
        "pilot_verdicts": _pilot_verdict_counts(subject_metrics),
        "metrics": out,
    }
