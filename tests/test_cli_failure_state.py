from __future__ import annotations

from mous_pipeline.cli import _failed_run_state_payload


def test_failed_run_state_payload_preserves_completed_stage_progress():
    existing = {
        "subject": "A2009",
        "status": "running",
        "selected_stages": ["m1", "m2", "m3", "m4", "m4_trial"],
        "current_stage": "m4_trial",
        "current_stage_description": "Builds trial-level MEG features for stats.",
        "current_stage_started_at": 123.0,
        "stage_index": 5,
        "stage_total": 5,
        "completed_stages": ["m1", "m2", "m3", "m4"],
        "stage_timings_s": {"m1": 0.1, "m2": 97.5, "m3": 5.2, "m4": 13.0},
        "started_at": 100.0,
    }

    payload = _failed_run_state_payload(
        existing,
        subject="A2009",
        selected_stages=["m1"],
        error=ValueError("metadata mismatch"),
        now=200.0,
    )

    assert payload["status"] == "failed"
    assert payload["completed_stages"] == ["m1", "m2", "m3", "m4"]
    assert payload["stage_timings_s"]["m2"] == 97.5
    assert payload["stage_index"] == 5
    assert payload["stage_total"] == 5
    assert payload["started_at"] == 100.0
    assert payload["updated_at"] == 200.0
    assert payload["current_stage"] is None
    assert payload["current_stage_description"] is None
    assert payload["error"] == "metadata mismatch"
