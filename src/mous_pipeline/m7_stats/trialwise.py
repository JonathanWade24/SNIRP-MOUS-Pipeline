"""Trial-wise models for Aim 1 and coupling analyses."""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import ttest_ind
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict


def logreg_condition_from_prestim(x: np.ndarray, y: np.ndarray) -> float:
    """Cross-validated AUC for condition decoding from one feature."""
    model = LogisticRegression(max_iter=500, solver="lbfgs")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    prob = cross_val_predict(model, x.reshape(-1, 1), y, cv=cv, method="predict_proba")[:, 1]
    return float(roc_auc_score(y, prob))


def n400m_condition_t(n400m: np.ndarray, condition: np.ndarray) -> float:
    """Two-sample t-statistic of ZINNEN vs WOORDEN for N400m amplitude."""
    z = n400m[condition == "ZINNEN"]
    w = n400m[condition == "WOORDEN"]
    stat = ttest_ind(z, w, equal_var=False, nan_policy="omit")
    return float(stat.statistic)


def lme_block_control(df: pd.DataFrame, formula: str) -> tuple[float | None, pd.DataFrame]:
    """
    Fit mixed model with block random intercept and return p-value for pos_in_block.

    Returns (p_value, tidy_table).
    """
    model = smf.mixedlm(formula=formula, data=df, groups=df["block_id"])
    fit = model.fit(reml=False, method="lbfgs", maxiter=200, disp=False)
    pval = fit.pvalues.get("pos_in_block")
    tidy = pd.DataFrame(
        {
            "term": fit.params.index.astype(str),
            "estimate": fit.params.to_numpy(dtype=float),
            "pvalue": [float(fit.pvalues.get(k, np.nan)) for k in fit.params.index],
        }
    )
    return (float(pval) if pval is not None else None), tidy
