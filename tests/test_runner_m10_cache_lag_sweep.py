from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from mous_pipeline.config import FmriConfig, PipelineConfig
from mous_pipeline.m9_orchestration.runner import run_subject


def test_m10_cache_hit_still_generates_hrf_lag_sweep_tables(tmp_path, monkeypatch) -> None:
    subject = "A2003"
    data_root = tmp_path / "bids"
    derivatives_root = tmp_path / "derivatives"
    cfg = PipelineConfig(data_root=data_root, derivatives_root=derivatives_root)
    cfg.fmri = FmriConfig(
        skip_fmriprep=True,
        fmriprep_output="",
        hrf_lag_sweep_s=[-2.0, 0.0, 2.0],
    )
    cfg.pipeline["strict_stage_failures"] = False

    # Prime the m10 cache and raw-BIDS BOLD path so only lag sweep work is needed.
    m10_out_dir = derivatives_root / subject / "m10_fmri"
    m10_out_dir.mkdir(parents=True, exist_ok=True)
    cached_joined = m10_out_dir / f"{subject}_trials_joined.csv"
    pd.DataFrame(
        {
            "trial_id": [0, 1],
            "condition": ["ZINNEN", "WOORDEN"],
            "pos_in_block": [0, 1],
            "mtg_beta": [0.1, 0.2],
        }
    ).to_csv(cached_joined, index=False)

    func_dir = data_root / f"sub-{subject}" / "func"
    func_dir.mkdir(parents=True, exist_ok=True)
    (func_dir / f"sub-{subject}_task-auditory_bold.nii.gz").write_text("dummy")
    # Prevent runner pre-m10 setup from trying to load rest MEG data.
    m9_out_dir = derivatives_root / subject / "m9_orchestration"
    m9_out_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "dirs_zinnen",
        "dirs_woorden",
        "dirs_rest",
        "sliding_dci_zinnen",
        "dci_zinnen",
        "dci_woorden",
        "dci_rest",
        "sliding_t",
    ):
        np.save(m9_out_dir / f"sub-{subject}_{name}.npy", np.array([0.0], dtype=float))
    np.save(m9_out_dir / f"sub-{subject}_sensor_xy.npy", np.array([[0.0, 0.0]], dtype=float))
    np.savez(m9_out_dir / f"sub-{subject}_epoch_shape.npz", n_epochs=1, n_channels=1, n_times=1)

    trials = pd.DataFrame({"condition": ["ZINNEN", "WOORDEN"]})
    trial_meta = pd.DataFrame(
        {
            "trial_id": [0, 1],
            "onset": [0.0, 2.0],
            "condition": ["ZINNEN", "WOORDEN"],
            "block_id": [0, 0],
            "pos_in_block": [0, 1],
        }
    )
    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.parse_events", lambda *_a, **_k: trials)
    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.make_events_metadata", lambda *_a, **_k: trial_meta)
    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.render_aim2_group", lambda *_a, **_k: None)

    def _fake_trialwise_betas(
        _bold_path: str,
        events_df: pd.DataFrame,
        _tr: float,
        *,
        atlas: str,
        roi: str,
        n_jobs: int,
        onset_shift_s: float = 0.0,
    ) -> pd.DataFrame:
        _ = (atlas, roi, n_jobs)
        return pd.DataFrame(
            {
                "trial_id": events_df["trial_id"].to_numpy(),
                "mtg_beta": [0.5 + onset_shift_s, 1.0 + onset_shift_s],
            }
        )

    monkeypatch.setattr("mous_pipeline.m10_fmri.glm.trialwise_betas", _fake_trialwise_betas)

    result = run_subject(subject, cfg, only={"m10"}, assume_upstream_done=True)

    assert result.metrics.get("m10_cache_hit") is True
    lag_tables = result.metrics.get("m10_hrf_lag_sweep_tables")
    assert isinstance(lag_tables, dict)
    assert set(lag_tables.keys()) == {"-2.000s", "+0.000s", "+2.000s"}
    for lag_path in lag_tables.values():
        assert Path(lag_path).exists()
