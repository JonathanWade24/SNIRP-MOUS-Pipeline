"""Module 7 circular stats."""

from __future__ import annotations

import numpy as np


def rayleigh_p(angles: np.ndarray) -> float:
    try:
        import pycircstat

        return float(pycircstat.tests.rayleigh(angles)[1])
    except Exception:
        n = len(angles)
        r = np.abs(np.sum(np.exp(1j * angles)))
        z = r**2 / n
        p = np.exp(-z) * (
            1 + (2 * z - z**2) / (4 * n) - (24 * z - 132 * z**2 + 76 * z**3 - 9 * z**4) / (288 * n**2)
        )
        return float(np.clip(p, 0, 1))
