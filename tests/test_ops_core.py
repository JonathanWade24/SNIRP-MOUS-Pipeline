from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mous_pipeline.ops.actions import (
    build_bem_submit_cmd,
    build_recon_submit_cmd,
    build_submit_cmd,
    compute_undownloaded_subjects,
    parse_sbatch_job_id,
)
from mous_pipeline.config import RuntimeOverrides
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


def test_build_submit_cmd_applies_runtime_overrides_over_preset() -> None:
    preset = WorkflowPreset(
        name="full_submit",
        description="",
        mode="submit",
        fetch_missing=False,
        include_m5=False,
        dry_run=False,
    )
    cmd = build_submit_cmd(
        preset,
        config="configs/palmetto_hpcnirc_fmri.yaml",
        subjects=["A2002"],
        account="abc123",
        partition="hpcnirc",
        time_limit="12:00:00",
        mem="256G",
        cpus_per_task="8",
        overrides=RuntimeOverrides(fetch_missing=True, include_m5=True, dry_run=True),
    )
    assert "--fetch-missing" in cmd
    assert "--include-m5" in cmd
    assert "--dry-run" in cmd


def test_state_migration_seeds_recent_configs_and_defaults(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        """
{
  "last_config": "configs/legacy.yaml",
  "defaults": {"account": "acct"},
  "workflow_presets": {},
  "recent_jobs": []
}
""".strip()
    )
    loaded = load_state(path=state_path)
    assert loaded.last_config == "configs/legacy.yaml"
    assert loaded.recent_configs[0] == "configs/legacy.yaml"
    assert isinstance(loaded.run_overrides_defaults, dict)


def test_submit_flag_contract_with_palmetto_wrapper() -> None:
    script = Path("scripts/palmetto_submit.sh").read_text()
    expected_flags = ["--fetch-missing", "--include-m5", "--dry-run"]
    for flag in expected_flags:
        assert flag in script


def test_build_recon_submit_cmd_preview() -> None:
    cmd = build_recon_submit_cmd(
        config="configs/palmetto_hpcnirc_fmri.yaml",
        subjects=["A2002", "A2003"],
        account="abc123",
        partition="hpcnirc",
        time_limit="12:00:00",
        mem="16G",
        cpus_per_task="4",
        dry_run=True,
    )
    assert cmd[0] == "scripts/palmetto_recon_all.sh"
    assert "--subjects" in cmd and "A2002,A2003" in cmd
    assert "--dry-run" in cmd


def test_build_bem_submit_cmd_preview() -> None:
    cmd = build_bem_submit_cmd(
        config="configs/palmetto_hpcnirc_fmri.yaml",
        subjects=["A2002", "A2003"],
        account="abc123",
        partition="hpcnirc",
        time_limit="04:00:00",
        mem="16G",
        cpus_per_task="2",
        dependency="afterok:12345",
        dry_run=True,
    )
    assert cmd[0] == "scripts/palmetto_prep_bem.sh"
    assert "--subjects" in cmd and "A2002,A2003" in cmd
    assert "--dependency" in cmd and "afterok:12345" in cmd
    assert "--dry-run" in cmd


def test_compute_undownloaded_subjects() -> None:
    missing = compute_undownloaded_subjects(
        local_subjects=["A2002"],
        remote_subjects=["A2002", "A2003", "sub-A2004"],
    )
    assert missing == ["A2003", "A2004"]
