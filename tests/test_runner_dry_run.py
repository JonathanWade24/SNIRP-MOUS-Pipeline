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
