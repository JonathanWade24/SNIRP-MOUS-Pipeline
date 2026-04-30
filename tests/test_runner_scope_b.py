from __future__ import annotations

import numpy as np
import pandas as pd

from mous_pipeline.m7_stats.trialwise import lme_block_control
from mous_pipeline.m9_orchestration.runner import (
    _guarded_prestim_auc,
    _m12_z_threshold_decision,
    _prestim_diagnostics,
)


def test_prestim_diagnostics_flags_degenerate_distribution():
    x = np.ones(12, dtype=float)
    y = np.array([0, 1] * 6, dtype=int)
    diag = _prestim_diagnostics(x, y)
    assert diag["is_degenerate"] is True
    assert diag["n_unique_finite"] == 1


def test_guarded_auc_returns_nan_for_single_class_labels():
    x = np.linspace(0.1, 1.0, 10)
    y = np.ones(10, dtype=int)
    auc, reason, diag = _guarded_prestim_auc(x, y)
    assert np.isnan(auc)
    assert reason == "degenerate_prestim_distribution_or_labels"
    assert diag["is_degenerate"] is True


def test_m12_z_threshold_decision_marks_pass():
    decision = _m12_z_threshold_decision(2.4, 1.96)
    assert decision["passes_z_threshold"] is True
    assert decision["z_margin"] > 0


def test_lme_block_control_can_report_non_default_term():
    rng = np.random.default_rng(42)
    df = pd.DataFrame(
        {
            "dci_trial": rng.normal(size=80),
            "condition": np.where(np.arange(80) % 2 == 0, "ZINNEN", "WOORDEN"),
            "pos_in_block": np.tile(np.arange(10), 8),
            "first_trial": np.tile([1] + [0] * 9, 8),
            "block_id": np.repeat(np.arange(8), 10),
        }
    )
    pval, tidy = lme_block_control(
        df,
        "dci_trial ~ C(condition) + pos_in_block + first_trial",
        term="first_trial",
    )
    assert pval is None or np.isfinite(pval)
    assert "term" in tidy.columns
