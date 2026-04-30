import numpy as np
import pytest

mne = pytest.importorskip("mne")

from mous_pipeline.m12_wave_validation.compare import confound_null_dci
from mous_pipeline.m12_wave_validation.simulate import simulate_two_dipoles


def test_two_dipole_null_z_is_finite():
    sfreq = 100.0
    info = mne.create_info([f"MLT{n:03d}" for n in range(10)], sfreq=sfreq, ch_types="mag")
    data = np.random.RandomState(1).randn(20, 10, 100) * 1e-13
    epochs = mne.EpochsArray(data, info, tmin=-0.5, verbose="ERROR")
    sim = simulate_two_dipoles(epochs, n_trials=20, snr=1.0)
    real_dci = np.random.RandomState(2).rand(20)
    null_dci = np.abs(sim.mean(axis=(1, 2)))
    summary = confound_null_dci(real_dci, null_dci)
    assert np.isfinite(summary["z"])
    assert "wave_detected" in summary
    assert "z_threshold" in summary
