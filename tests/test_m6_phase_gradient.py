import numpy as np

from mous_pipeline.m6_waves.phase_gradient import directional_consistency_index


def test_direction_arrays_match_reference_dci(pilot_artifact_dir):
    z = np.load(pilot_artifact_dir / "sub-A2002_dirs_zinnen.npy")
    w = np.load(pilot_artifact_dir / "sub-A2002_dirs_woorden.npy")
    r = np.load(pilot_artifact_dir / "sub-A2002_dirs_rest.npy")

    assert np.isclose(directional_consistency_index(z), 0.0034748795723150354, atol=1e-12)
    assert np.isclose(directional_consistency_index(w), 0.005126065743286809, atol=1e-12)
    assert np.isclose(directional_consistency_index(r), 0.003949796958230425, atol=1e-12)
