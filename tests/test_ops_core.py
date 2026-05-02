from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import mous_pipeline.ops.actions as actions
from mous_pipeline.ops.actions import (
    MODE_TO_PRESET_DEFAULTS,
    build_bem_submit_cmd,
    build_group_cmd,
    build_recon_submit_cmd,
    build_submit_cmd,
    compile_intent_plan,
    compute_undownloaded_subjects,
    detect_intent_capabilities,
    intent_profile_from_legacy_preset,
    merge_subject_ids,
    recommend_resources,
    resolve_repo_root,
    parse_sbatch_job_id,
)
from mous_pipeline.ops.monitor import sinfo_partition
from mous_pipeline.config import RuntimeOverrides
from mous_pipeline.ops.models import OpsState, WorkflowPreset
from mous_pipeline.ops.monitor import classify_failure
from mous_pipeline.ops.state import default_intent_profiles, default_presets, load_state, preset_from_run_options, save_state


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


def test_build_submit_cmd_includes_extra_runtime_args() -> None:
    preset = WorkflowPreset(name="full_submit", description="", mode="submit")
    cmd = build_submit_cmd(
        preset,
        config="configs/palmetto_hpcnirc_fmri.yaml",
        subjects=["A2002"],
        account="abc123",
        partition="hpcnirc",
        time_limit="12:00:00",
        mem="256G",
        cpus_per_task="8",
        extra_runtime_args=["--meg-skip", "m5,m10,m11", "--skip-fmriprep-submit"],
    )
    assert "--meg-skip" in cmd
    assert "m5,m10,m11" in cmd
    assert "--skip-fmriprep-submit" in cmd


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


def test_mode_to_preset_defaults_cover_all_modes() -> None:
    assert {"full_pipeline", "meg_only", "fmri_only", "download_only"} <= set(MODE_TO_PRESET_DEFAULTS)
    assert MODE_TO_PRESET_DEFAULTS["download_only"].fetch_missing is True
    assert MODE_TO_PRESET_DEFAULTS["fmri_only"].extra_args == ["--subjects"]


def test_preset_from_run_options_round_trip() -> None:
    preset = preset_from_run_options(
        name="my_saved",
        mode="full_pipeline",
        fetch_missing=True,
        include_m5=True,
        dry_run=False,
        bids_convert=True,
        bids_validate=False,
    )
    assert preset.name == "my_saved"
    assert preset.mode == "full_pipeline"
    assert preset.fetch_missing is True
    assert preset.include_m5 is True
    assert preset.bids_convert is True


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
    assert isinstance(loaded.workflow_presets, dict)


def test_submit_flag_contract_with_palmetto_wrapper() -> None:
    script = Path("scripts/palmetto_submit.sh").read_text()
    expected_flags = [
        "--fetch-missing",
        "--include-m5",
        "--dry-run",
        "--skip-m5",
        "--meg-skip",
        "--skip-fmriprep-submit",
        "--skip-fmri-stages-submit",
        "--skip-group",
        "--skip-aim1-audit",
    ]
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


def test_add_undownloaded_survives_reload_merge() -> None:
    merged = merge_subject_ids(["A2002"], ["A2002", "A2003"])
    assert merged == ["A2002", "A2003"]


def test_build_group_cmd_defaults() -> None:
    cmd = build_group_cmd(derivatives_root="derivatives/mous_pipeline", subjects=["A2002", "sub-A2003"])
    assert cmd[:3] == ["mous-pipeline", "group", "--derivatives-root"]
    assert "--subjects" in cmd
    assert "A2002,A2003" in cmd


def test_build_group_cmd_quarto_only() -> None:
    cmd = build_group_cmd(derivatives_root="derivatives/mous_pipeline", quarto_only=True)
    assert "--quarto-only" in cmd


def test_sinfo_partition_missing_sinfo_returns_none(monkeypatch) -> None:
    monkeypatch.setattr("mous_pipeline.ops.monitor._run_text", lambda _cmd: "")
    assert sinfo_partition("hpcnirc") is None


def test_recommend_resources_from_partition_info() -> None:
    rec = recommend_resources(
        n_subjects=5,
        partition_info={"partition": "hpcnirc", "max_node_mem_gb": 256, "max_node_cpus": 32},
        peak_rss_gb=12.0,
    )
    assert rec["suggested_mem"].endswith("G")
    assert int(rec["suggested_cpus_per_task"]) >= 1
    assert rec["suggested_parallel_subjects"] >= 1


def _fake_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "MOUS"
    (repo / "scripts").mkdir(parents=True)
    (repo / "src" / "mous_pipeline").mkdir(parents=True)
    (repo / "configs").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'mous-pipeline'\n")
    submit = repo / "scripts" / "palmetto_submit.sh"
    submit.write_text("#!/usr/bin/env bash\n")
    config = repo / "configs" / "palmetto.yaml"
    config.write_text("derivatives_root: /scratch/example/derivatives\n")
    return repo, config


def test_resolve_repo_root_prefers_config_checkout_over_cwd(tmp_path: Path, monkeypatch) -> None:
    repo, config = _fake_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(home)

    assert resolve_repo_root(repo_root=home, config_path=str(config)) == repo


def test_execute_submit_cmd_runs_repo_script_from_repo_root(tmp_path: Path, monkeypatch) -> None:
    repo, config = _fake_repo(tmp_path)
    captured = {}

    def fake_run_cmd(cmd: list[str], *, cwd: Path | None = None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, stdout="Submitted batch job 42\n", stderr="")

    monkeypatch.setattr(actions, "run_cmd", fake_run_cmd)
    job, proc = actions.execute_submit_cmd(
        ["scripts/palmetto_submit.sh", "--config", str(config)],
        config_path=str(config),
        subjects=["A2002"],
    )

    assert proc.returncode == 0
    assert job is not None and job.job_id == "42"
    assert captured["cwd"] == repo
    assert captured["cmd"][0] == str(repo / "scripts" / "palmetto_submit.sh")
    assert captured["cmd"][2] == str(config)


def test_execute_submit_cmd_preserves_external_relative_config(tmp_path: Path, monkeypatch) -> None:
    repo, _ = _fake_repo(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    config = external / "ad_hoc.yaml"
    config.write_text("derivatives_root: /scratch/example/adhoc\n")
    captured = {}

    def fake_run_cmd(cmd: list[str], *, cwd: Path | None = None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, stdout="Submitted batch job 44\n", stderr="")

    monkeypatch.chdir(external)
    monkeypatch.setenv("MOUS_REPO_ROOT", str(repo))
    monkeypatch.setattr(actions, "run_cmd", fake_run_cmd)
    job, _ = actions.execute_submit_cmd(
        ["scripts/palmetto_submit.sh", "--config", "ad_hoc.yaml"],
        config_path="ad_hoc.yaml",
        subjects=["A2002"],
    )

    assert job is not None and job.job_id == "44"
    assert captured["cwd"] == repo
    assert captured["cmd"][0] == str(repo / "scripts" / "palmetto_submit.sh")
    assert captured["cmd"][2] == str(config)


def test_detached_driver_anchors_script_without_moving_logs(tmp_path: Path, monkeypatch) -> None:
    repo, config = _fake_repo(tmp_path)
    derivatives_root = tmp_path / "derivatives"
    captured = {}

    def fake_run_cmd(cmd: list[str], *, cwd: Path | None = None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, stdout="Submitted batch job 43\n", stderr="")

    monkeypatch.setattr(actions, "run_cmd", fake_run_cmd)
    job, _ = actions.submit_detached_driver(
        ["scripts/palmetto_submit.sh", "--config", str(config)],
        config_path=str(config),
        subjects=["A2002"],
        account="acct",
        partition="hpcnirc",
        time_limit="01:00:00",
        mem="8G",
        cpus_per_task="2",
        venv_path=str(tmp_path / "venv"),
        derivatives_root=str(derivatives_root),
        repo_root=tmp_path / "home",
    )

    assert job is not None and job.job_id == "43"
    assert captured["cwd"] == repo
    sbatch_cmd = captured["cmd"]
    wrapped = sbatch_cmd[sbatch_cmd.index("--wrap") + 1]
    assert f"cd {repo}" in wrapped
    assert str(repo / "scripts" / "palmetto_submit.sh") in wrapped
    assert str(config) in wrapped
    assert sbatch_cmd[sbatch_cmd.index("--output") + 1] == str(
        derivatives_root / "slurm" / "mous_driver_%j.out"
    )
    assert sbatch_cmd[sbatch_cmd.index("--error") + 1] == str(
        derivatives_root / "slurm" / "mous_driver_%j.err"
    )


def test_default_intent_profiles_present() -> None:
    intents = default_intent_profiles()
    assert {"quick_qc", "full_subject", "full_cohort", "group_reports_only", "recover_failed"} <= set(intents)


def test_intent_profile_from_legacy_preset() -> None:
    preset = WorkflowPreset(name="legacy_full", description="legacy", mode="submit", include_m5=True)
    profile, note = intent_profile_from_legacy_preset(preset)
    assert profile.intent_id == "legacy_legacy_full"
    assert profile.default_include_m5 is True
    assert "Legacy preset translated" in note


def test_compile_intent_plan_dependency_closure(tmp_path: Path) -> None:
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("data_root: .\nderivatives_root: derivatives\n")
    profile = default_intent_profiles()["quick_qc"]
    plan = compile_intent_plan(profile, config_path=str(cfg), subjects=["A2002"])
    assert "m1" in plan.resolved_stages
    assert "m3" in plan.resolved_stages
    assert plan.command_kind == "submit"
    assert "--skip-fmriprep-submit" in plan.runtime_args
    assert "--meg-skip" in plan.runtime_args


def test_detect_intent_capabilities_graceful_on_bad_config(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(":\n")
    caps = detect_intent_capabilities(str(bad))
    assert set(caps.keys()) == {"has_repocli", "has_quarto", "has_freesurfer", "has_fmri"}
