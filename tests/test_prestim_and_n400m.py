import numpy as np
import pandas as pd
import pytest

mne = pytest.importorskip("mne")

from mous_pipeline.config import PipelineConfig
from mous_pipeline.m4_features.n400m import n400m_amplitude
from mous_pipeline.m4_features.prestim import prestim_beta_power


def _fake_epochs():
    sfreq = 100.0
    n_trials, n_ch, n_t = 12, 6, 200
    times = np.arange(n_t) / sfreq - 0.5
    data = np.random.RandomState(42).randn(n_trials, n_ch, n_t) * 1e-13
    # Inject stronger pre-stim beta in first half.
    pre_idx = (times >= -0.5) & (times <= 0.0)
    data[:6, :, pre_idx] += np.sin(2 * np.pi * 20 * times[pre_idx])[None, None, :] * 1e-12
    info = mne.create_info([f"MLT{n:03d}" for n in range(n_ch)], sfreq=sfreq, ch_types="mag")
    return mne.EpochsArray(data, info, tmin=-0.5, verbose="ERROR")


def test_prestim_beta_and_n400m_shapes(repo_root):
    epochs = _fake_epochs()
    cfg = PipelineConfig(data_root=repo_root, derivatives_root=repo_root / "derivatives" / "test_tmp")
    meta = pd.DataFrame(
        {
            "trial_id": np.arange(len(epochs)),
            "condition": ["ZINNEN"] * (len(epochs) // 2) + ["WOORDEN"] * (len(epochs) // 2),
            "block_id": [0] * len(epochs),
            "pos_in_block": np.arange(len(epochs)),
        }
    )
    prestim = prestim_beta_power(epochs, "TEST", cfg, meta)
    n400m = n400m_amplitude(epochs, "TEST", cfg, meta)
    assert prestim.shape == (len(epochs),)
    assert n400m.shape == (len(epochs),)
    npz = np.load(repo_root / "derivatives" / "test_tmp" / "TEST" / "m4_features" / "TEST_prestim_beta.npz")
    assert "condition_diag_ks_p" in npz
    assert "aim1_prestim_condition_t_map" in npz
    assert npz["prestim_beta_by_channel"].shape[0] == len(epochs)
    npz_n400 = np.load(repo_root / "derivatives" / "test_tmp" / "TEST" / "m4_features" / "TEST_n400m.npz")
    assert int(npz_n400["n_channels_used"]) == len(epochs.ch_names)
    assert str(npz_n400["sensor_prefix"]) == "MLT"
    assert float(npz_n400["tmin"]) == 0.3
    assert float(npz_n400["tmax"]) == 0.5


def test_n400m_accepts_topography_weights(repo_root):
    epochs = _fake_epochs()
    cfg = PipelineConfig(data_root=repo_root, derivatives_root=repo_root / "derivatives" / "test_tmp")
    meta = pd.DataFrame(
        {
            "trial_id": np.arange(len(epochs)),
            "condition": ["ZINNEN"] * (len(epochs) // 2) + ["WOORDEN"] * (len(epochs) // 2),
            "block_id": [0] * len(epochs),
            "pos_in_block": np.arange(len(epochs)),
        }
    )
    weights = np.linspace(1.0, 2.0, len(epochs.ch_names))
    n400m = n400m_amplitude(epochs, "TEST", cfg, meta, topography_weights=weights)
    assert n400m.shape == (len(epochs),)
    npz_n400 = np.load(repo_root / "derivatives" / "test_tmp" / "TEST" / "m4_features" / "TEST_n400m.npz")
    assert bool(npz_n400["has_topography_weights"]) is True


def test_trial_meta_must_match_epoch_count(repo_root):
    epochs = _fake_epochs()
    cfg = PipelineConfig(data_root=repo_root, derivatives_root=repo_root / "derivatives" / "test_tmp")
    meta = pd.DataFrame(
        {
            "trial_id": np.arange(len(epochs) + 1),
            "condition": ["ZINNEN"] * (len(epochs) // 2 + 1) + ["WOORDEN"] * (len(epochs) // 2),
            "block_id": [0] * (len(epochs) + 1),
            "pos_in_block": np.arange(len(epochs) + 1),
        }
    )
    with pytest.raises(ValueError, match="trial_meta length does not match epoch count"):
        prestim_beta_power(epochs, "TEST", cfg, meta)
    with pytest.raises(ValueError, match="trial_meta length does not match epoch count"):
        n400m_amplitude(epochs, "TEST", cfg, meta)
