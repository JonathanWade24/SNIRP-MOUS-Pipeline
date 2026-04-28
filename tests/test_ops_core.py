from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mous_pipeline.ops.actions import build_submit_cmd, parse_sbatch_job_id
from mous_pipeline.ops.models import OpsState, WorkflowPreset
from mous_pipeline.ops.monitor import classify_failure
from mous_pipeline.ops.state import default_presets, load_state, save_state


def test_state_persistence_round_trip(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    st = OpsState()
    st.defaults["account"] = "myacct"
    st.workflow_presets["custom"] = WorkflowPreset(
        name="custom",
        description="custom preset",
        mode="submit",
        include_m5=True,
    )
    save_state(st, path=state_path)
    loaded = load_state(path=state_path)
    assert loaded.defaults["account"] == "myacct"
    assert loaded.workflow_presets["custom"].include_m5 is True


def test_build_submit_cmd_for_m5_preset() -> None:
    preset = WorkflowPreset(
        name="m5_enabled_submit",
        description="",
        mode="submit",
        include_m5=True,
    )
    cmd = build_submit_cmd(
        preset,
        config="configs/palmetto_hpcnirc_fmri.yaml",
        subjects=["A2002", "A2003"],
        account="abc123",
        partition="hpcnirc",
        time_limit="12:00:00",
        mem="256G",
        cpus_per_task="8",
    )
    assert "--include-m5" in cmd
    assert cmd[0] == "scripts/palmetto_submit.sh"


def test_parse_sbatch_job_id_and_failure_classification() -> None:
    assert parse_sbatch_job_id("Submitted batch job 123456") == "123456"
    assert classify_failure("slurmstepd: error: Detected 1 oom-kill event") == "oom"


def test_default_presets_keep_command_keys_compatible() -> None:
    presets = default_presets()
    # Keep historical keys stable for CLI/state compatibility.
    assert {"full_submit", "m5_enabled_submit", "fmriprep_only_submit"} <= set(presets)

    cmd = build_submit_cmd(
        presets["full_submit"],
        config="configs/palmetto_hpcnirc_fmri.yaml",
        subjects=["A2002"],
        account="abc123",
        partition="hpcnirc",
        time_limit="12:00:00",
        mem="256G",
        cpus_per_task="8",
    )
    assert "--include-m5" not in cmd
    assert "--dry-run" not in cmd
