import pandas as pd

from mous_pipeline.config import PipelineConfig
from mous_pipeline.m9_orchestration.runner import run_subject


def test_run_subject_dry_run_returns_without_data_access():
    cfg = PipelineConfig()
    result = run_subject("A9999", cfg, dry_run=True)
    assert result.metrics["dry_run"] is True
    assert "selected_stages" in result.metrics


def test_run_subject_m10_only_allows_assume_upstream_done():
    cfg = PipelineConfig()
    with_assumption = run_subject(
        "A9999",
        cfg,
        only={"m10"},
        dry_run=True,
        assume_upstream_done=True,
    )
    assert with_assumption.metrics["dry_run"] is True
    assert with_assumption.metrics["selected_stages"] == ["m10"]


def test_run_subject_m7_without_m6a_cache_skips_instead_of_crashing(tmp_path, monkeypatch):
    subject = "A9999"
    cfg = PipelineConfig(data_root=tmp_path / "bids", derivatives_root=tmp_path / "derivatives")
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

    def _unexpected_perm_test(*_a, **_k):
        raise AssertionError("m7 should not run DCI permutation tests without m6a outputs")

    monkeypatch.setattr("mous_pipeline.m9_orchestration.runner.perm_test_dci", _unexpected_perm_test)

    result = run_subject(subject, cfg, only={"m7"}, assume_upstream_done=True)

    assert result.status == "completed_with_skips"
    assert "m7" in result.skipped_stages
    assert "m6a outputs unavailable" in result.metrics["m7_skipped_reason"]
    assert "p_task_vs_rest" not in result.metrics
