from mous_pipeline.config import (
    RuntimeOverrides,
    apply_runtime_overrides,
    load_config,
    resolve_runtime_overrides,
)


def test_load_config_reads_hrf_lag_sweep_and_m12_threshold(tmp_path):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "data_root: '.'",
                "derivatives_root: 'derivatives'",
                "fmri:",
                "  hrf_lag_sweep_s: [-2.0, 0.0, 2.0]",
                "  onset_shift_s: 1.0",
                "features:",
                "  n400m_window_s: [0.25, 0.55]",
                "  n400m_sensor_prefix: 'MLT'",
                "  n400m_topography_weights_path: 'weights.npy'",
                "wave_validation:",
                "  z_threshold: 2.5",
            ]
        )
    )
    cfg = load_config(cfg_path)
    assert cfg.fmri.hrf_lag_sweep_s == [-2.0, 0.0, 2.0]
    assert cfg.fmri.onset_shift_s == 1.0
    assert cfg.features.n400m_window_s == (0.25, 0.55)
    assert cfg.features.n400m_sensor_prefix == "MLT"
    assert cfg.features.n400m_topography_weights_path == "weights.npy"
    assert cfg.wave_validation.z_threshold == 2.5


def test_resolve_runtime_overrides_uses_last_non_none_layer():
    resolved = resolve_runtime_overrides(
        RuntimeOverrides(fetch_missing=False, include_m5=False, dry_run=False),
        RuntimeOverrides(fetch_missing=True),
        RuntimeOverrides(include_m5=True),
        RuntimeOverrides(dry_run=True),
    )
    assert resolved.fetch_missing is True
    assert resolved.include_m5 is True
    assert resolved.dry_run is True


def test_apply_runtime_overrides_writes_pipeline_knobs(tmp_path):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("data_root: '.'\nderivatives_root: 'derivatives'\n")
    cfg = load_config(cfg_path)
    apply_runtime_overrides(
        cfg,
        RuntimeOverrides(reuse_fmriprep=True, allow_m11_cached_joined=True),
    )
    assert cfg.pipeline["m10_reuse_fmriprep"] is True
    assert cfg.pipeline["m11_allow_cached_joined"] is True
