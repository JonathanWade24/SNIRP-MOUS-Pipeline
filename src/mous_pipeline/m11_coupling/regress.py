"""MEG-fMRI coupling models."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
import statsmodels.formula.api as smf


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
    """Compute condition-wise partial Spearman and a mixed model summary."""
    out: dict[str, float | dict] = {}
    for condition in ["ZINNEN", "WOORDEN"]:
        subset = df[df["condition"] == condition]
        if len(subset) < 8:
            continue
        for feature in ["prestim_beta", "n400m", "dci_trial"]:
            r, p = partial_spearman(subset, feature, "mtg_beta", ["pos_in_block"])
            key = f"{condition.lower()}_{feature}_vs_mtg"
            out[key] = {"r": r, "p": p}
    if len(df) >= 10:
        fit = smf.ols("mtg_beta ~ prestim_beta + n400m + dci_trial + C(condition) + pos_in_block", data=df).fit()
        out["lme_like"] = {
            "r2": float(fit.rsquared),
            "p_prestim_beta": float(fit.pvalues.get("prestim_beta", np.nan)),
            "p_n400m": float(fit.pvalues.get("n400m", np.nan)),
            "p_dci_trial": float(fit.pvalues.get("dci_trial", np.nan)),
        }
    return out
