from mous_pipeline.m9_orchestration.runner import (
    RunResult,
    _mark_critical_failure,
    _strict_stage_failures_enabled,
)
from mous_pipeline.config import PipelineConfig
from mous_pipeline.cli import _verify_run_manifest


def test_mark_critical_failure_for_m10_blocks_downstream():
    result = RunResult(subject="A0001")
    state: dict[str, object] = {}
    blocked = _mark_critical_failure(
        result=result,
        state=state,
        stage="m10",
        error=RuntimeError("boom"),
        only=None,
        skip=None,
    )
    assert result.status == "failed"
    assert result.metrics["failed_stage"] == "m10"
    assert blocked == ["m11", "m12", "m8"]
    assert "m11" in result.skipped_stages
    assert state["error"] == "m10 failed: boom"


def test_mark_critical_failure_respects_stage_selection():
    result = RunResult(subject="A0001")
    state: dict[str, object] = {}
    blocked = _mark_critical_failure(
        result=result,
        state=state,
        stage="m10",
        error=RuntimeError("boom"),
        only={"m10", "m11"},
        skip=None,
    )
    assert blocked == ["m11"]
    assert result.metrics["blocked_stages"] == ["m11"]


def test_strict_stage_failures_defaults_to_false_without_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    cfg = PipelineConfig()
    assert _strict_stage_failures_enabled(cfg) is False


def test_strict_stage_failures_can_be_enabled_by_pipeline_config():
    cfg = PipelineConfig(pipeline={"strict_stage_failures": True})
    assert _strict_stage_failures_enabled(cfg) is True


def test_verify_run_manifest_requires_m5_skip_and_strict_fields():
    payload = {
        "metrics": {
            "run_status": "done",
            "skipped_stages": ["m5"],
            "m10_error": None,
            "m11_error": None,
        },
        "outputs": ["out.json"],
    }
    assert _verify_run_manifest(payload, require_skip_m5=True, strict_mode=True) == []


def test_verify_run_manifest_fails_for_missing_invariants():
    payload = {"metrics": {"run_status": "failed", "skipped_stages": []}, "outputs": []}
    errs = _verify_run_manifest(payload, require_skip_m5=True, strict_mode=True)
    assert any("run_status" in e for e in errs)
    assert any("m5" in e for e in errs)
