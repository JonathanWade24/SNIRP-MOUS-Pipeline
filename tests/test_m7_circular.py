import numpy as np

from mous_pipeline.m7_stats.circular import rayleigh_p


def test_rayleigh_p_is_finite_for_identical_angles():
    z = np.zeros(50)
    p = rayleigh_p(z)
    assert np.isfinite(p)
    assert 0.0 <= p <= 1.0
