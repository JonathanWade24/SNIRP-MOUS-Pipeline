"""Tests for MEG-fMRI coupling (m11) when MEG feature columns are optional."""

from __future__ import annotations

import numpy as np
import pandas as pd

from mous_pipeline.m11_coupling.regress import (
    MEG_COUPLING_FEATURES,
    hydrate_meg_features,
    run_coupling_models,
)


def _base_df(n_per_cond: int = 10) -> pd.DataFrame:
    n = n_per_cond * 2
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "trial_id": np.arange(n),
            "onset": np.linspace(0.0, float(n), n),
            "condition": ["ZINNEN"] * n_per_cond + ["WOORDEN"] * n_per_cond,
            "block_id": np.zeros(n),
            "pos_in_block": np.tile(np.arange(n_per_cond), 2),
            "mtg_beta": rng.standard_normal(n),
        }
    )


def test_run_coupling_models_full_meg_columns():
    df = _base_df(10)
    df["prestim_beta"] = np.linspace(0.1, 1.0, len(df))
    df["n400m"] = np.linspace(-0.5, 0.5, len(df))
    df["dci_trial"] = np.linspace(0.01, 0.02, len(df))

    out = run_coupling_models(df)

    assert out["features_used"] == list(MEG_COUPLING_FEATURES)
    assert out["feature_roles"]["prestim_beta"] == "primary"
    assert out["feature_roles"]["n400m"] == "exploratory"
    assert "zinnen_prestim_beta_vs_mtg" in out
    assert "woorden_dci_trial_vs_mtg" in out
    assert "p_fdr_bh" in out["zinnen_prestim_beta_vs_mtg"]
    assert "fdr_bh_condition_vs_mtg" in out
    assert "lme_like" in out
    assert "r2" in out["lme_like"]
    for key in ("p_prestim_beta", "p_n400m", "p_dci_trial"):
        assert key in out["lme_like"]
    for key in ("p_prestim_beta_fdr_bh", "p_n400m_fdr_bh", "p_dci_trial_fdr_bh"):
        assert key in out["lme_like"]


def test_run_coupling_models_dci_only_no_keyerror():
    df = _base_df(10)
    df["dci_trial"] = np.linspace(0.01, 0.03, len(df))

    out = run_coupling_models(df)

    assert out["features_used"] == ["dci_trial"]
    assert "zinnen_dci_trial_vs_mtg" in out
    assert "woorden_dci_trial_vs_mtg" in out
    assert "lme_like" in out
    assert np.isnan(out["lme_like"]["p_prestim_beta"])
    assert np.isnan(out["lme_like"]["p_n400m"])
    assert not np.isnan(out["lme_like"]["p_dci_trial"])


def test_hydrate_meg_features_adds_missing_cached_columns():
    joined = _base_df(10)
    joined["dci_trial"] = np.linspace(0.01, 0.03, len(joined))
    trial_features = pd.DataFrame(
        {
            "trial_id": joined["trial_id"],
            "prestim_beta": np.random.default_rng(1).standard_normal(len(joined)),
            "n400m": np.random.default_rng(2).standard_normal(len(joined)),
        }
    )

    hydrated, features = hydrate_meg_features(joined, trial_features)
    out = run_coupling_models(hydrated)

    assert features == ["prestim_beta", "n400m"]
    assert out["features_used"] == list(MEG_COUPLING_FEATURES)
    assert not np.isnan(out["lme_like"]["p_prestim_beta"])
    assert not np.isnan(out["lme_like"]["p_n400m"])


def test_hydrate_meg_features_fills_nulls_without_overwriting_values():
    joined = _base_df(5)
    joined["prestim_beta"] = [1.0, np.nan, 3.0, np.nan, 5.0, 6.0, np.nan, 8.0, 9.0, np.nan]
    trial_features = pd.DataFrame(
        {
            "trial_id": joined["trial_id"],
            "prestim_beta": np.arange(10.0, 20.0),
        }
    )

    hydrated, features = hydrate_meg_features(
        joined,
        trial_features,
        features=("prestim_beta",),
    )

    assert features == ["prestim_beta"]
    assert hydrated.loc[0, "prestim_beta"] == 1.0
    assert hydrated.loc[1, "prestim_beta"] == 11.0


def test_run_coupling_models_mtg_only_returns_minimal():
    df = _base_df(10)
    out = run_coupling_models(df)

    assert out["features_used"] == []
    assert "lme_like" not in out
    assert not any(k.endswith("_vs_mtg") for k in out if isinstance(k, str))
