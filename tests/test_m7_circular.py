import numpy as np

from mous_pipeline.m7_stats.circular import rayleigh_p


def test_rayleigh_matches_pilot(pilot_artifact_dir):
    z = np.load(pilot_artifact_dir / "sub-A2002_dirs_zinnen.npy")
    p = rayleigh_p(z)
    assert np.isclose(p, 0.683373867600939, atol=1e-12)
