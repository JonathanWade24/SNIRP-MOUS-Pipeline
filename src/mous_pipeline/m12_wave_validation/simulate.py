"""Null simulations for traveling-wave confound checks."""

from __future__ import annotations

import numpy as np


def simulate_two_dipoles(epochs, *, n_trials: int, snr: float, random_state: int = 42):
    """
    Create a two-source confound surrogate in sensor space.

    This is a lightweight approximation for CI/testing environments:
    two independent latent oscillators projected to random sensor weights.
    """
    rng = np.random.default_rng(random_state)
    data = epochs.get_data(picks="meg")
    n_ch = data.shape[1]
    n_t = data.shape[2]
    t = np.linspace(0, n_t / epochs.info["sfreq"], n_t, endpoint=False)
    w1 = rng.normal(size=n_ch)
    w2 = rng.normal(size=n_ch)
    sim = np.zeros((n_trials, n_ch, n_t), dtype=float)
    for i in range(n_trials):
        f1 = 16.0 + rng.normal(scale=0.5)
        f2 = 24.0 + rng.normal(scale=0.5)
        s1 = np.sin(2 * np.pi * f1 * t + rng.uniform(0, 2 * np.pi))
        s2 = np.sin(2 * np.pi * f2 * t + rng.uniform(0, 2 * np.pi))
        clean = np.outer(w1, s1) + np.outer(w2, s2)
        noise = rng.normal(scale=np.std(clean) / max(snr, 1e-6), size=clean.shape)
        sim[i] = clean + noise
    return sim
