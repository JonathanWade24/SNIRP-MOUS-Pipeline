import os
import stat
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_fake_mous_pipeline(bin_dir: Path) -> None:
    fake = bin_dir / "mous-pipeline"
    fake.write_text("#!/usr/bin/env bash\necho fake mous-pipeline \"$@\"\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)


def _write_minimal_config(cfg_path: Path, *, data_root: Path, derivatives_root: Path) -> None:
    cfg_path.write_text(
        (
            f'data_root: "{data_root}"\n'
            f'derivatives_root: "{derivatives_root}"\n'
            "subjects:\n"
            '  - "A2002"\n'
            "source:\n"
            '  subjects_dir: ""\n'
            "  use_fsaverage: true\n"
            '  trans: "fsaverage"\n'
            "fmri:\n"
            '  fmriprep_output: "derivatives/fmriprep"\n'
            "  skip_fmriprep: true\n"
            '  neurodesk_module: ""\n'
        )
    )


def _base_env(fake_bin: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
    }


def test_palmetto_submit_include_m5_changes_meg_skip(tmp_path: Path):
    data_root = tmp_path / "data"
    derivatives_root = tmp_path / "derivatives"
    (data_root / "sub-A2002").mkdir(parents=True)
    cfg = tmp_path / "cfg.yaml"
    _write_minimal_config(cfg, data_root=data_root, derivatives_root=derivatives_root)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_mous_pipeline(fake_bin)
    env = _base_env(fake_bin)

    default_proc = subprocess.run(
        [
            "bash",
            "scripts/palmetto_submit.sh",
            "--config",
            str(cfg),
            "--subjects",
            "A2002",
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--skip m5,m10,m11" in default_proc.stdout
    # Clarity labels should reflect workflow tracks (not Aim-number names).
    assert "[dry-run][fmri] note: fMRI preprocessing runs as detached array jobs" in default_proc.stdout
    assert "[dry-run][meg] " not in default_proc.stdout
    assert "[dry-run][meg-group] mous-pipeline group" in default_proc.stdout
    assert "[dry-run][meg-group] python" in default_proc.stdout

    # Keep execution order stable while labels change.
    out = default_proc.stdout
    i_audit = out.index("[meg-trial]")
    i_fmri = out.index("[fmri] submitting fMRI preprocessing array")
    i_subject = out.index("[meg-subject]")
    i_group = out.index("[meg-group] Running MEG group aggregation")
    assert i_audit < i_fmri < i_subject < i_group

    include_proc = subprocess.run(
        [
            "bash",
            "scripts/palmetto_submit.sh",
            "--config",
            str(cfg),
            "--subjects",
            "A2002",
            "--include-m5",
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--skip m10,m11" in include_proc.stdout
    assert "--skip m5,m10,m11" not in include_proc.stdout


def test_palmetto_recon_all_dry_run_uses_hpcnirc_and_array(tmp_path: Path):
    data_root = tmp_path / "data"
    derivatives_root = tmp_path / "derivatives"
    cfg = tmp_path / "cfg.yaml"
    _write_minimal_config(cfg, data_root=data_root, derivatives_root=derivatives_root)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_mous_pipeline(fake_bin)
    env = _base_env(fake_bin)

    proc = subprocess.run(
        ["bash", "scripts/palmetto_recon_all.sh", "--config", str(cfg), "--dry-run"],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "--partition hpcnirc" in proc.stdout
    assert "--time 24:00:00" in proc.stdout
    assert "--mem 64G" in proc.stdout
    assert "--cpus-per-task 8" in proc.stdout
    assert "--array 0-0" in proc.stdout
    assert "run_recon_all_subject.sh" in proc.stdout


def test_palmetto_prep_bem_dry_run_uses_hpcnirc_and_array(tmp_path: Path):
    data_root = tmp_path / "data"
    derivatives_root = tmp_path / "derivatives"
    cfg = tmp_path / "cfg.yaml"
    _write_minimal_config(cfg, data_root=data_root, derivatives_root=derivatives_root)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_mous_pipeline(fake_bin)
    env = _base_env(fake_bin)

    proc = subprocess.run(
        ["bash", "scripts/palmetto_prep_bem.sh", "--config", str(cfg), "--dry-run"],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "--partition hpcnirc" in proc.stdout
    assert "--time 04:00:00" in proc.stdout
    assert "--mem 16G" in proc.stdout
    assert "--cpus-per-task 2" in proc.stdout
    assert "--array 0-0" in proc.stdout
    assert "run_prep_bem_subject.sh" in proc.stdout


def test_run_prep_bem_subject_skips_when_surfaces_exist(tmp_path: Path):
    subjects_file = tmp_path / "subjects.txt"
    subjects_file.write_text("A2002\n")
    subjects_dir = tmp_path / "freesurfer"
    bem_dir = subjects_dir / "sub-A2002" / "bem"
    bem_dir.mkdir(parents=True)
    (bem_dir / "inner_skull.surf").write_text("ok")
    (bem_dir / "outer_skull.surf").write_text("ok")
    (bem_dir / "outer_skin.surf").write_text("ok")

    proc = subprocess.run(
        [
            "bash",
            "scripts/run_prep_bem_subject.sh",
            "--subjects-file",
            str(subjects_file),
            "--subjects-dir",
            str(subjects_dir),
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "SLURM_ARRAY_TASK_ID": "0"},
        text=True,
        capture_output=True,
        check=True,
    )
    assert "[bem] skip subject=sub-A2002" in proc.stdout


def test_run_aims_priority_dry_run_prints_dependent_fmri_stages_submit(tmp_path: Path):
    data_root = tmp_path / "data"
    derivatives_root = tmp_path / "derivatives"
    (data_root / "sub-A2002").mkdir(parents=True)
    cfg = tmp_path / "cfg.yaml"
    _write_minimal_config(cfg, data_root=data_root, derivatives_root=derivatives_root)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_mous_pipeline(fake_bin)
    env = _base_env(fake_bin)

    proc = subprocess.run(
        [
            "bash",
            "scripts/run_aims_priority.sh",
            "--config",
            str(cfg),
            "--subjects",
            "A2002",
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "[dry-run][slurm] sbatch --job-name mous_fmri_stages" in proc.stdout
    assert "--dependency afterok:" in proc.stdout
    assert "scripts/run_fmri_stages.sh" in proc.stdout
