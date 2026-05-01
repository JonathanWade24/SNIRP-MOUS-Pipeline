from __future__ import annotations

from mous_pipeline.m9_orchestration.runner import _preserve_unselected_stage_metrics_for_reports


def test_report_only_preserves_prior_downstream_metrics() -> None:
    current = {
        "selected_stages": ["m8"],
        "n_trials": 240,
    }
    previous = {
        "selected_stages": ["m10", "m11", "m12", "m8"],
        "n_trials": 999,
        "m10_hrf_lag_selection": {"strategy": "max_abs_condition_prestim_correlation"},
        "m11_coupling_hrf_lag_sweep": {"+4.000s": {"zinnen_prestim_beta_vs_mtg": {"r": 0.2}}},
        "m12_decision": {"passes_z_threshold": False},
        "aim3_wave_detected": False,
        "source_dci_zinnen": 0.61,
        "m5_n_stcs": 60,
    }

    preserved = _preserve_unselected_stage_metrics_for_reports(current, previous, {"m8"})

    assert current["n_trials"] == 240
    assert current["m10_hrf_lag_selection"] == previous["m10_hrf_lag_selection"]
    assert current["m11_coupling_hrf_lag_sweep"] == previous["m11_coupling_hrf_lag_sweep"]
    assert current["m12_decision"] == previous["m12_decision"]
    assert current["aim3_wave_detected"] is False
    assert current["source_dci_zinnen"] == 0.61
    assert current["m5_n_stcs"] == 60
    assert set(preserved) == set(current["m8_preserved_previous_metric_keys"])


def test_report_preserve_skips_selected_stage_metrics() -> None:
    current = {"selected_stages": ["m8", "m11"]}
    previous = {
        "m10_hrf_lag_selection": {"strategy": "cached"},
        "m11_coupling": {"old": True},
    }

    _preserve_unselected_stage_metrics_for_reports(current, previous, {"m8", "m11"})

    assert current["m10_hrf_lag_selection"] == {"strategy": "cached"}
    assert "m11_coupling" not in current
