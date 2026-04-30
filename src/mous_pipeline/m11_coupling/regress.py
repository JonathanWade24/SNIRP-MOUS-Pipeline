"""MEG-fMRI coupling models."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import statsmodels.formula.api as smf

MEG_COUPLING_FEATURES: tuple[str, ...] = ("prestim_beta", "n400m", "dci_trial")


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
    out: dict[str, float | dict | list[str]] = {"features_used": list(available)}

    if "mtg_beta" not in df.columns or not available:
        return out

    for condition in ["ZINNEN", "WOORDEN"]:
        subset = df[df["condition"] == condition]
        if len(subset) < 8:
            continue
        for feature in available:
            r, p = partial_spearman(subset, feature, "mtg_beta", ["pos_in_block"])
            key = f"{condition.lower()}_{feature}_vs_mtg"
            out[key] = {"r": r, "p": p}

    if len(df) >= 10 and available:
        rhs = " + ".join(available)
        formula = f"mtg_beta ~ {rhs} + C(condition) + pos_in_block"
        fit = smf.ols(formula, data=df).fit()
        lme_like: dict[str, float] = {"r2": float(fit.rsquared)}
        for name in MEG_COUPLING_FEATURES:
            pkey = "p_dci_trial" if name == "dci_trial" else f"p_{name}"
            lme_like[pkey] = float(fit.pvalues.get(name, np.nan))
        out["lme_like"] = lme_like

    return out
