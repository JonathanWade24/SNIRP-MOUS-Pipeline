"""Module 7 permutation tests."""

from __future__ import annotations

import numpy as np


def perm_test_dci(dci_a: np.ndarray, dci_b: np.ndarray, n_permutations: int = 5000, seed: int = 42):
    rng = np.random.default_rng(seed)
    obs_diff = float(np.mean(dci_a) - np.mean(dci_b))
    pooled = np.concatenate([dci_a, dci_b])
    n_a = len(dci_a)
    null = np.zeros(n_permutations, dtype=float)
    for i in range(n_permutations):
        perm = rng.permutation(pooled)
        null[i] = np.mean(perm[:n_a]) - np.mean(perm[n_a:])
    p = float(np.mean(null >= obs_diff))
    return obs_diff, p
