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


def _write_fake_apptainer(bin_dir: Path) -> None:
    fake = bin_dir / "apptainer"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$FAKE_APPTAINER_LOG\"\n"
        "touch \"$FAKE_WS_DIR/${FAKE_SUBJECT}__inner_skull_surface\"\n"
        "touch \"$FAKE_WS_DIR/${FAKE_SUBJECT}__outer_skull_surface\"\n"
        "touch \"$FAKE_WS_DIR/${FAKE_SUBJECT}__outer_skin_surface\"\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)


def _write_minimal_config(cfg_path: Path, *, data_root: Path, derivatives_root: Path) -> None:
    fs_license_file = derivatives_root / "license.txt"
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
            f'  fs_license_file: "{fs_license_file}"\n'
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
    assert f"MOUS_FREESURFER_LICENSE={derivatives_root / 'license.txt'}" in proc.stdout
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


def test_run_prep_bem_subject_passes_license_to_container(tmp_path: Path):
    subjects_file = tmp_path / "subjects.txt"
    subjects_file.write_text("A2002\n")
    subjects_dir = tmp_path / "freesurfer"
    (subjects_dir / "sub-A2002" / "mri").mkdir(parents=True)
    (subjects_dir / "sub-A2002" / "mri" / "T1.mgz").write_text("t1")
    ws_dir = subjects_dir / "sub-A2002" / "bem" / "watershed"
    license_file = tmp_path / "license.txt"
    license_file.write_text("license")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_apptainer(fake_bin)
    apptainer_log = tmp_path / "apptainer_args.txt"

    env = {
        **_base_env(fake_bin),
        "SLURM_ARRAY_TASK_ID": "0",
        "MOUS_FREESURFER_CONTAINER": str(tmp_path / "fmriprep.sif"),
        "MOUS_FREESURFER_LICENSE": str(license_file),
        "FAKE_APPTAINER_LOG": str(apptainer_log),
        "FAKE_WS_DIR": str(ws_dir),
        "FAKE_SUBJECT": "sub-A2002",
    }

    subprocess.run(
        [
            "bash",
            "scripts/run_prep_bem_subject.sh",
            "--subjects-file",
            str(subjects_file),
            "--subjects-dir",
            str(subjects_dir),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    args = apptainer_log.read_text()
    assert f"{license_file.parent}:{license_file.parent}" in args
    assert f"FS_LICENSE={license_file}" in args
    assert (subjects_dir / "sub-A2002" / "bem" / "inner_skull.surf").exists()
    assert (subjects_dir / "sub-A2002" / "bem" / "outer_skull.surf").exists()
    assert (subjects_dir / "sub-A2002" / "bem" / "outer_skin.surf").exists()


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
    # Use afterany + --kill-on-invalid-dep=no so a partially-failed or already
    # cleared fMRIPrep array does not torpedo the dependent submission.
    assert "--dependency afterany:" in proc.stdout
    assert "--kill-on-invalid-dep=no" in proc.stdout
    assert "afterok:" not in proc.stdout
    assert "scripts/run_fmri_stages.sh" in proc.stdout


def test_run_fmri_stages_dry_run_includes_m8(tmp_path: Path):
    data_root = tmp_path / "data"
    derivatives_root = tmp_path / "derivatives"
    cfg = tmp_path / "cfg.yaml"
    _write_minimal_config(cfg, data_root=data_root, derivatives_root=derivatives_root)
    subjects_file = tmp_path / "subjects.txt"
    subjects_file.write_text("A2002\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_mous_pipeline(fake_bin)
    env = _base_env(fake_bin)

    proc = subprocess.run(
        [
            "bash",
            "scripts/run_fmri_stages.sh",
            "--config",
            str(cfg),
            "--subjects-file",
            str(subjects_file),
            "--deriv-root",
            str(derivatives_root),
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert '--only "m8,m10,m11,m12"' not in proc.stdout
    assert "--only m8,m10,m11,m12" in proc.stdout
    assert "--preflight-quarto-env" in proc.stdout


def test_run_fmri_stages_loads_r_module_before_pipeline(tmp_path: Path):
    data_root = tmp_path / "data"
    derivatives_root = tmp_path / "derivatives"
    cfg = tmp_path / "cfg.yaml"
    _write_minimal_config(cfg, data_root=data_root, derivatives_root=derivatives_root)
    subjects_file = tmp_path / "subjects.txt"
    subjects_file.write_text("A2002\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_mous_pipeline(fake_bin)

    fake_r_dir = tmp_path / "fake_r"
    fake_r_dir.mkdir()
    fake_rscript = fake_r_dir / "Rscript"
    fake_rscript.write_text("#!/usr/bin/env bash\nexit 0\n")
    fake_rscript.chmod(fake_rscript.stat().st_mode | stat.S_IXUSR)

    module_log = tmp_path / "module.log"
    bash_env = tmp_path / "bash_env"
    bash_env.write_text(
        "\n".join(
            [
                "module() {",
                '  echo "$*" >> "$MODULE_LOG"',
                '  if [[ "$1" == "load" ]]; then',
                '    export PATH="$FAKE_R_DIR:$PATH"',
                "  fi",
                "}",
                "",
            ]
        )
    )

    env = _base_env(fake_bin)
    env["BASH_ENV"] = str(bash_env)
    env["FAKE_R_DIR"] = str(fake_r_dir)
    env["MODULE_LOG"] = str(module_log)
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    proc = subprocess.run(
        [
            "bash",
            "scripts/run_fmri_stages.sh",
            "--config",
            str(cfg),
            "--subjects-file",
            str(subjects_file),
            "--deriv-root",
            str(derivatives_root),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert module_log.read_text().strip() == "load r/4.5.0"
    assert "[fmri-stages][r] Loading R module: r/4.5.0" in proc.stdout
    assert "[fmri-stages][r] Rscript:" in proc.stdout
    assert "--preflight-quarto-env" in proc.stdout
