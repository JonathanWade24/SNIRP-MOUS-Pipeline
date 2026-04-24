import numpy as np
import pytest

from mous_pipeline.m6_waves.phase_gradient import directional_consistency_index


def test_directional_consistency_index_aligned():
    d = np.zeros(64)
    assert directional_consistency_index(d) == pytest.approx(1.0)


def test_directional_consistency_index_cancels():
    d = np.array([0.0, np.pi] * 32)
    assert directional_consistency_index(d) == pytest.approx(0.0, abs=1e-12)
