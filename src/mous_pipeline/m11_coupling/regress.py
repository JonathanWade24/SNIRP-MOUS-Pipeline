"""MEG-fMRI coupling models."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import statsmodels.formula.api as smf

MEG_COUPLING_FEATURES: tuple[str, ...] = ("prestim_beta", "n400m", "dci_trial")
PRIMARY_MEG_FEATURES: tuple[str, ...] = ("prestim_beta",)


def _bh_fdr(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR-adjusted p-values."""
    m = len(pvals)
    if m == 0:
        return []
    p = np.asarray(pvals, dtype=float)
    order = np.argsort(p)
    ranked = p[order]
    adjusted = np.empty(m, dtype=float)
    prev = 1.0
    for i in range(m - 1, -1, -1):
        rank = i + 1
        val = min(prev, ranked[i] * m / rank)
        adjusted[i] = val
        prev = val
    out = np.empty(m, dtype=float)
    out[order] = np.clip(adjusted, 0.0, 1.0)
    return out.tolist()


def hydrate_meg_features(
    joined_df: pd.DataFrame,
    trial_df: pd.DataFrame,
    *,
    features: tuple[str, ...] = MEG_COUPLING_FEATURES,
) -> tuple[pd.DataFrame, list[str]]:
    """Add missing MEG feature columns to a joined trial table by ``trial_id``.

    fMRI-only reruns often reuse an m10 joined CSV. If that CSV was written
    before cached m4_trial features were attached, m11 can still use those
    cached columns by hydrating them from the current trial table.
    """
    if "trial_id" not in joined_df.columns or "trial_id" not in trial_df.columns:
        return joined_df, []

    available = [feature for feature in features if feature in trial_df.columns]
    needed = [
        feature
        for feature in available
        if feature not in joined_df.columns or joined_df[feature].isna().any()
    ]
    if not needed:
        return joined_df, []

    out = joined_df.copy()
    feature_df = trial_df[["trial_id", *needed]].drop_duplicates("trial_id")
    merged = out.merge(feature_df, on="trial_id", how="left", suffixes=("", "__meg"))
    hydrated: list[str] = []

    for feature in needed:
        if feature in out.columns:
            source = f"{feature}__meg"
            if source not in merged.columns:
                continue
            before_nonnull = int(merged[feature].notna().sum())
            merged[feature] = merged[feature].combine_first(merged[source])
            merged = merged.drop(columns=[source])
            if int(merged[feature].notna().sum()) > before_nonnull:
                hydrated.append(feature)
        else:
            if feature in merged.columns and merged[feature].notna().any():
                hydrated.append(feature)

    return merged, hydrated


def partial_spearman(df: pd.DataFrame, feature: str, target: str, covars: list[str]) -> tuple[float, float]:
    """Approximate partial Spearman via rank-residualization."""
    ranked = df[[feature, target, *covars]].rank()
    x_formula = f"{feature} ~ {' + '.join(covars)}"
    y_formula = f"{target} ~ {' + '.join(covars)}"
    x_resid = smf.ols(x_formula, data=ranked).fit().resid
    y_resid = smf.ols(y_formula, data=ranked).fit().resid
    corr = spearmanr(x_resid, y_resid, nan_policy="omit")
    return float(corr.correlation), float(corr.pvalue)


def run_coupling_models(df: pd.DataFrame) -> dict:
    """Compute condition-wise partial Spearman and an OLS summary (trial-level).

    Only MEG columns that exist on ``df`` are used (e.g. ``m4_trial`` may have been
    skipped so ``prestim_beta`` / ``n400m`` are absent).
    """
    available = [c for c in MEG_COUPLING_FEATURES if c in df.columns]
    out: dict[str, float | dict | list[str]] = {
        "features_used": list(available),
        "feature_roles": {
            feature: ("primary" if feature in PRIMARY_MEG_FEATURES else "exploratory")
            for feature in available
        },
    }

    if "mtg_beta" not in df.columns or not available:
        return out

    per_condition_pvals: dict[str, list[tuple[str, float]]] = {"zinnen": [], "woorden": []}
    for condition in ["ZINNEN", "WOORDEN"]:
        subset = df[df["condition"] == condition]
        if len(subset) < 8:
            continue
        for feature in available:
            r, p = partial_spearman(subset, feature, "mtg_beta", ["pos_in_block"])
            condition_key = condition.lower()
            key = f"{condition_key}_{feature}_vs_mtg"
            out[key] = {"r": r, "p": p}
            per_condition_pvals[condition_key].append((key, p))

    fdr_condition: dict[str, dict[str, float]] = {}
    for condition_key, entries in per_condition_pvals.items():
        adj = _bh_fdr([p for _, p in entries])
        mapping: dict[str, float] = {}
        for (key, _), p_fdr in zip(entries, adj):
            if isinstance(out.get(key), dict):
                out[key]["p_fdr_bh"] = float(p_fdr)
            mapping[key] = float(p_fdr)
        if mapping:
            fdr_condition[condition_key] = mapping
    if fdr_condition:
        out["fdr_bh_condition_vs_mtg"] = fdr_condition
    out["m11_exploratory_features"] = [f for f in available if f not in PRIMARY_MEG_FEATURES]
    primary_feature = next((f for f in PRIMARY_MEG_FEATURES if f in available), None)
    if primary_feature is not None:
        out["m11_primary_feature"] = primary_feature
        primary_keys = [f"{cond}_{primary_feature}_vs_mtg" for cond in ("zinnen", "woorden")]
        primary_rows = [
            out[k]
            for k in primary_keys
            if isinstance(out.get(k), dict) and np.isfinite(float(out[k].get("r", np.nan)))
        ]
        if primary_rows:
            best_row = max(primary_rows, key=lambda row: abs(float(row.get("r", 0.0))))
            out["m11_primary_r"] = float(best_row["r"])
            out["m11_primary_p_fdr"] = float(best_row.get("p_fdr_bh", best_row.get("p", np.nan)))

    if len(df) >= 10 and available:
        rhs = " + ".join(available)
        formula = f"mtg_beta ~ {rhs} + C(condition) + pos_in_block"
        fit = smf.ols(formula, data=df).fit()
        lme_like: dict[str, float] = {"r2": float(fit.rsquared)}
        model_pvals: list[tuple[str, float]] = []
        for name in MEG_COUPLING_FEATURES:
            pkey = "p_dci_trial" if name == "dci_trial" else f"p_{name}"
            pval = float(fit.pvalues.get(name, np.nan))
            lme_like[pkey] = pval
            if name in available and np.isfinite(pval):
                model_pvals.append((pkey, pval))
        if model_pvals:
            adj = _bh_fdr([p for _, p in model_pvals])
            lme_like_fdr: dict[str, float] = {}
            for (pkey, _), p_fdr in zip(model_pvals, adj):
                lme_like_fdr[f"{pkey}_fdr_bh"] = float(p_fdr)
            lme_like.update(lme_like_fdr)
        out["lme_like"] = lme_like

    return out
