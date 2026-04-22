from mous_pipeline.config import PipelineConfig
from mous_pipeline.m9_orchestration.runner import run_subject


def test_run_subject_dry_run_returns_without_data_access():
    cfg = PipelineConfig()
    result = run_subject("A9999", cfg, dry_run=True)
    assert result.metrics["dry_run"] is True
    assert "selected_stages" in result.metrics
