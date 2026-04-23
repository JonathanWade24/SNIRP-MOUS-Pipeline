import numpy as np
import pandas as pd

from mous_pipeline.m7_stats.trialwise import lme_block_control


def test_block_position_covariate_controls_confound():
    rng = np.random.default_rng(0)
    rows = []
    for block_id in range(8):
        for pos in range(12):
            condition = "ZINNEN" if pos % 2 == 0 else "WOORDEN"
            dci = 0.2 + 0.03 * pos + rng.normal(0, 0.02)
            rows.append({"block_id": block_id, "pos_in_block": pos, "condition": condition, "dci_trial": dci})
    df = pd.DataFrame(rows)
    p_block, tidy = lme_block_control(df, "dci_trial ~ C(condition) + pos_in_block")
    assert p_block is not None
    assert np.isfinite(p_block)
    assert "pos_in_block" in set(tidy["term"])
