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
