from mous_pipeline.config import load_config


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
                "wave_validation:",
                "  z_threshold: 2.5",
            ]
        )
    )
    cfg = load_config(cfg_path)
    assert cfg.fmri.hrf_lag_sweep_s == [-2.0, 0.0, 2.0]
    assert cfg.fmri.onset_shift_s == 1.0
    assert cfg.wave_validation.z_threshold == 2.5
