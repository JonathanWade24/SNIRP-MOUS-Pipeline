from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from ..config import RuntimeOverrides, load_config, resolve_runtime_overrides
from ..m9_orchestration.parallelization_plan import recommend_subject_parallelism
from ..m0_intake.repocli_rdr import build_repocli_ls_command, parse_repocli_ls_subjects, repocli_available
from ..stage_dependencies import STAGE_DEPENDENCIES, STAGE_ORDER
from .models import IntentExecutionPlan, IntentProfile, JobRecord, WorkflowPreset

MODE_TO_PRESET_DEFAULTS: dict[str, WorkflowPreset] = {
    "full_pipeline": WorkflowPreset(
        name="full_submit",
        description="Multimodal driver with detached fMRI preprocessing",
        mode="submit",
    ),
    "meg_only": WorkflowPreset(
        name="meg_only",
        description="MEG-focused submit mode",
        mode="submit",
    ),
    "fmri_only": WorkflowPreset(
        name="fmriprep_only_submit",
        description="fMRI preprocessing only",
        mode="submit",
        extra_args=["--subjects"],
    ),
    "download_only": WorkflowPreset(
        name="download_only",
        description="Download only",
        mode="download",
        fetch_missing=True,
    ),
}


def detect_intent_capabilities(config_path: str) -> dict[str, bool]:
    caps = {
        "has_repocli": repocli_available(),
        "has_quarto": shutil.which("quarto") is not None,
        "has_freesurfer": False,
        "has_fmri": False,
    }
    try:
        cfg = load_config(Path(config_path).expanduser())
        caps["has_freesurfer"] = bool(getattr(getattr(cfg, "source", None), "subjects_dir", ""))
        fmri_cfg = getattr(cfg, "fmri", None)
        caps["has_fmri"] = bool(fmri_cfg and (getattr(fmri_cfg, "bold_path", "") or not getattr(fmri_cfg, "skip_fmriprep", True)))
    except Exception:
        return caps
    return caps


def _closure_with_notes(requested: list[str]) -> tuple[list[str], list[str]]:
    selected = {s for s in requested if s in STAGE_ORDER}
    notes: list[str] = []
    changed = True
    while changed:
        changed = False
        for stage in list(selected):
            for dep in STAGE_DEPENDENCIES.get(stage, set()):
                if dep not in selected:
                    selected.add(dep)
                    notes.append(f"{stage} requires {dep}")
                    changed = True
    ordered = [s for s in STAGE_ORDER if s in selected]
    return ordered, notes


def intent_profile_from_legacy_preset(preset: WorkflowPreset) -> tuple[IntentProfile, str]:
    if preset.mode == "download":
        profile = IntentProfile(
            intent_id=f"legacy_{preset.name}",
            label=f"Legacy: {preset.name}",
            description=preset.description or "Legacy preset translated to intent profile.",
            requested_stages=["m1", "m2", "m3", "m4", "m6a", "m7", "m8", "m9"],
            default_fetch_missing=True,
            default_include_m5=bool(preset.include_m5),
            default_dry_run=bool(preset.dry_run),
            legacy_preset_name=preset.name,
        )
        return profile, "Legacy download preset translated to intent workflow."
    profile = IntentProfile(
        intent_id=f"legacy_{preset.name}",
        label=f"Legacy: {preset.name}",
        description=preset.description or "Legacy preset translated to intent profile.",
        requested_stages=["m1", "m2", "m3", "m4", "m4_trial", "m6a", "m7", "m8", "m9"],
        default_fetch_missing=bool(preset.fetch_missing),
        default_include_m5=bool(preset.include_m5),
        default_dry_run=bool(preset.dry_run),
        legacy_preset_name=preset.name,
    )
    return profile, "Legacy preset translated to intent profile with compatibility mode."


def compile_intent_plan(
    profile: IntentProfile,
    *,
    config_path: str,
    subjects: list[str],
    preferred_constraint: str = "balanced",
) -> IntentExecutionPlan:
    capabilities = detect_intent_capabilities(config_path)
    resolved_stages, dep_notes = _closure_with_notes(profile.requested_stages)
    warnings: list[str] = []
    resolved_flags = {
        "fetch_missing": bool(profile.default_fetch_missing),
        "include_m5": bool(profile.default_include_m5),
        "dry_run": bool(profile.default_dry_run),
        "bids_convert": False,
        "bids_validate": False,
    }
    if not capabilities["has_repocli"] and resolved_flags["fetch_missing"]:
        resolved_flags["fetch_missing"] = False
        warnings.append("repocli unavailable: disabled fetch-missing behavior.")
    if not capabilities["has_freesurfer"] and resolved_flags["include_m5"]:
        resolved_flags["include_m5"] = False
        warnings.append("FreeSurfer subjects_dir not configured: disabled m5 include.")
    if "m10" in resolved_stages and not capabilities["has_fmri"]:
        warnings.append("fMRI capabilities not detected; m10/m11 may be skipped at runtime.")
    if profile.target == "group" and not capabilities["has_quarto"]:
        warnings.append("Quarto not detected; group report regeneration may fail.")
    if preferred_constraint == "fastest":
        resolved_flags["dry_run"] = False
    if preferred_constraint == "safest":
        resolved_flags["dry_run"] = True
        warnings.append("Constraint=safest enabled dry-run by default.")
    base_preset_name = profile.legacy_preset_name or "full_submit"
    if base_preset_name == "bids_convert_validate":
        base_preset_name = "full_submit"
    runtime_args: list[str] = []
    selected = set(resolved_stages)
    # Encode intent-resolved behavior into runtime args consumed by palmetto wrappers.
    if "m10" not in selected and "m11" not in selected:
        runtime_args.extend(["--skip-fmriprep-submit", "--skip-fmri-stages-submit"])
    if "m5" not in selected:
        runtime_args.append("--skip-m5")
    meg_subject_stages = {"m1", "m2", "m3", "m4", "m4_trial", "m5", "m6a", "m6_extra", "m7", "m8", "m9", "m12"}
    meg_skip = [s for s in STAGE_ORDER if s in meg_subject_stages and s not in selected]
    if meg_skip:
        runtime_args.extend(["--meg-skip", ",".join(meg_skip)])
    if "m8" not in selected and "m9" not in selected:
        runtime_args.append("--skip-group")
    if "m4_trial" not in selected:
        runtime_args.append("--skip-aim1-audit")
    return IntentExecutionPlan(
        intent_id=profile.intent_id,
        command_kind=profile.target,
        base_preset_name=base_preset_name,
        resolved_stages=resolved_stages,
        resolved_flags=resolved_flags,
        runtime_args=runtime_args,
        dependency_notes=dep_notes,
        warnings=warnings,
        legacy_translation_note=(
            f"Using legacy preset compatibility path: {profile.legacy_preset_name}"
            if profile.legacy_preset_name
            else ""
        ),
    )


def _is_repo_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").is_file()
        and (path / "scripts" / "palmetto_submit.sh").is_file()
        and (path / "src" / "mous_pipeline").is_dir()
    )


def _find_repo_root(start: Path) -> Path | None:
    current = start.expanduser()
    if current.is_file():
        current = current.parent
    current = current.resolve()
    for candidate in (current, *current.parents):
        if _is_repo_root(candidate):
            return candidate
    return None


def resolve_repo_root(*, repo_root: Path | None = None, config_path: str | None = None) -> Path:
    """Resolve the project checkout that owns the Palmetto helper scripts."""
    starts: list[Path] = []
    env_root = os.environ.get("MOUS_REPO_ROOT")
    if repo_root is not None:
        starts.append(repo_root)
    if env_root:
        starts.append(Path(env_root))
    if config_path:
        cfg = Path(config_path).expanduser()
        starts.append(cfg if cfg.is_absolute() else Path.cwd() / cfg)
    starts.extend([Path.cwd(), Path(__file__).resolve()])
    for start in starts:
        found = _find_repo_root(start)
        if found is not None:
            return found
    return (repo_root or Path.cwd()).expanduser().resolve()


def _anchor_repo_script(cmd: list[str], repo_root: Path) -> list[str]:
    if not cmd:
        return cmd
    executable = Path(cmd[0]).expanduser()
    if executable.is_absolute():
        return cmd
    if executable.parts[:1] == ("scripts",):
        anchored = repo_root / executable
        if anchored.exists():
            return [str(anchored), *cmd[1:]]
    return cmd


def _preserve_config_path(cmd: list[str], original_cwd: Path, repo_root: Path) -> list[str]:
    if "--config" not in cmd:
        return cmd
    index = cmd.index("--config") + 1
    if index >= len(cmd):
        return cmd
    config = Path(cmd[index]).expanduser()
    if config.is_absolute():
        return cmd
    if (repo_root / config).exists():
        return cmd
    original_config = (original_cwd / config).resolve()
    if original_config.exists():
        updated = list(cmd)
        updated[index] = str(original_config)
        return updated
    return cmd


def prepare_repo_command(cmd: list[str], repo_root: Path, *, original_cwd: Path | None = None) -> list[str]:
    """Anchor repo helper scripts while preserving relative config semantics."""
    prepared = _preserve_config_path(cmd, original_cwd or Path.cwd(), repo_root)
    return _anchor_repo_script(prepared, repo_root)


def discover_subjects(config_path: str, data_root: str | None = None) -> list[str]:
    subjects: set[str] = set()
    cfg_path = Path(config_path).expanduser()
    cfg_obj = None
    if cfg_path.exists():
        try:
            cfg_obj = load_config(cfg_path)
        except Exception:
            cfg_obj = None
    effective_data_root = data_root
    if not effective_data_root and cfg_obj is not None:
        effective_data_root = str(cfg_obj.data_root)
    if effective_data_root:
        for p in Path(effective_data_root).expanduser().glob("sub-*"):
            if p.is_dir():
                subjects.add(p.name.removeprefix("sub-"))
    if cfg_obj is not None:
        subjects.update(s.removeprefix("sub-") for s in cfg_obj.subjects)
    elif cfg_path.exists():
        txt = cfg_path.read_text()
        for m in re.findall(r'^\s*-\s*"?([A-Za-z0-9_-]+)"?\s*$', txt, flags=re.M):
            if m.startswith("A") or m.startswith("sub-"):
                subjects.add(m.removeprefix("sub-"))
    return sorted(subjects)


def discover_remote_subjects(config_path: str) -> tuple[list[str], str | None]:
    """Query RDR via repocli and return available subject IDs."""
    if not repocli_available():
        return [], "repocli is not on PATH."
    cfg = load_config(Path(config_path).expanduser().resolve())
    collection = str(getattr(cfg.rdr, "collection_path", "")).strip()
    if not collection:
        return [], "rdr.collection_path is empty in config."
    proc = run_cmd(build_repocli_ls_command(collection), cwd=Path.cwd())
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or (proc.stdout or "").strip() or "unknown repocli error"
        return [], f"Failed to list RDR subjects: {err}"
    return parse_repocli_ls_subjects(proc.stdout or ""), None


def compute_undownloaded_subjects(local_subjects: list[str], remote_subjects: list[str]) -> list[str]:
    local = {s.removeprefix("sub-") for s in local_subjects}
    remote = {s.removeprefix("sub-") for s in remote_subjects}
    return sorted(remote - local)


def merge_subject_ids(discovered: list[str], selected: list[str]) -> list[str]:
    discovered_clean = [s.removeprefix("sub-") for s in discovered if s.strip()]
    selected_clean = [s.removeprefix("sub-") for s in selected if s.strip()]
    discovered_set = set(discovered_clean)
    return list(dict.fromkeys(discovered_clean + [s for s in selected_clean if s not in discovered_set]))


def build_submit_cmd(
    preset: WorkflowPreset,
    *,
    config: str,
    subjects: list[str],
    account: str,
    partition: str,
    time_limit: str,
    mem: str,
    cpus_per_task: str,
    overrides: RuntimeOverrides | None = None,
    extra_runtime_args: list[str] | None = None,
    force: bool = False,
) -> list[str]:
    preset_overrides = RuntimeOverrides(
        fetch_missing=preset.fetch_missing,
        include_m5=preset.include_m5,
        dry_run=preset.dry_run,
    )
    resolved = resolve_runtime_overrides(preset_overrides, overrides)
    cmd = [
        "scripts/palmetto_submit.sh",
        "--config",
        config,
        "--subjects",
        ",".join(subjects),
        "--account",
        account,
        "--partition",
        partition,
        "--time",
        time_limit,
        "--mem",
        mem,
        "--cpus-per-task",
        cpus_per_task,
    ]
    if resolved.fetch_missing:
        cmd.append("--fetch-missing")
    if resolved.include_m5:
        cmd.append("--include-m5")
    if resolved.dry_run:
        cmd.append("--dry-run")
    if force:
        cmd.append("--force")
    cmd.extend(preset.extra_args)
    if extra_runtime_args:
        cmd.extend(extra_runtime_args)
    return cmd


def validate_config_path(raw_path: str) -> tuple[bool, str]:
    """Return (ok, absolute_path_or_error_message) for a pipeline YAML."""
    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    if not p.exists():
        return False, f"Config not found: {p}"
    try:
        load_config(p)
    except Exception as exc:
        return False, f"Invalid config: {exc}"
    return True, str(p)


def _m6a_cache_paths(m9_dir: Path, subject: str) -> list[Path]:
    """Paths that must exist for m6a cache hit (matches runner heuristic)."""
    s = subject.removeprefix("sub-")
    keys = [
        ("dirs_z", f"sub-{s}_dirs_zinnen.npy"),
        ("dirs_w", f"sub-{s}_dirs_woorden.npy"),
        ("dirs_r", f"sub-{s}_dirs_rest.npy"),
        ("sliding_z", f"sub-{s}_sliding_dci_zinnen.npy"),
        ("dci_z", f"sub-{s}_dci_zinnen.npy"),
        ("dci_w", f"sub-{s}_dci_woorden.npy"),
        ("dci_r", f"sub-{s}_dci_rest.npy"),
        ("sliding_t", f"sub-{s}_sliding_t.npy"),
    ]
    paths = [m9_dir / name for _, name in keys]
    paths.append(m9_dir / f"sub-{s}_sensor_xy.npy")
    paths.append(m9_dir / f"sub-{s}_epoch_shape.npz")
    alpha = [
        f"sub-{s}_alpha_dirs_zinnen.npy",
        f"sub-{s}_alpha_dirs_woorden.npy",
        f"sub-{s}_alpha_dirs_rest.npy",
        f"sub-{s}_alpha_dci_zinnen.npy",
        f"sub-{s}_alpha_dci_woorden.npy",
        f"sub-{s}_alpha_dci_rest.npy",
    ]
    paths.extend(m9_dir / n for n in alpha)
    return paths


def subject_stage_cache_hit(derivatives_root: str, subject: str, stage: str) -> bool:
    """Best-effort artifact presence check (file existence; m4_trial skips npz alignment check)."""
    s = subject.removeprefix("sub-")
    root = Path(derivatives_root).expanduser()
    m4_dir = root / f"sub-{s}" / "m4_features"
    m9_dir = root / f"sub-{s}" / "m9_orchestration"
    m10_dir = root / f"sub-{s}" / "m10_fmri"
    if stage == "m4":
        return (m4_dir / f"{s}_beta_analytic.npz").is_file() and (m4_dir / f"{s}_beta_psd.npz").is_file()
    if stage == "m4_trial":
        return (m4_dir / f"{s}_prestim_beta.npz").is_file() and (m4_dir / f"{s}_n400m.npz").is_file()
    if stage == "m6a":
        return m9_dir.is_dir() and all(p.is_file() for p in _m6a_cache_paths(m9_dir, s))
    if stage == "m10":
        return (m10_dir / f"{s}_trials_joined.csv").is_file()
    return False


def get_stage_cache_counts(derivatives_root: str, subjects: list[str], stage: str) -> tuple[int, int]:
    """Return (n_cached, n_total) for a cacheable stage."""
    clean = [x.removeprefix("sub-") for x in subjects if x.strip()]
    if not clean:
        return 0, 0
    hits = sum(1 for s in clean if subject_stage_cache_hit(derivatives_root, s, stage))
    return hits, len(clean)


def get_subject_cache_summary(derivatives_root: str, subject: str) -> str:
    """Compact cache line for subject rows (m4 / m6a / m10 only — main cost centers)."""
    parts: list[str] = []
    for label, st in (("m4", "m4"), ("m6a", "m6a"), ("m10", "m10")):
        hit = subject_stage_cache_hit(derivatives_root, subject, st)
        parts.append(f"{label}{'✓' if hit else '·'}")
    return " ".join(parts)


def custom_intent_profile_from_stages(
    requested_stages: list[str],
    *,
    intent_id: str = "custom",
    label: str = "Custom",
    description: str = "Custom stage selection from Ops UI.",
    default_fetch_missing: bool = False,
    default_include_m5: bool = False,
    default_dry_run: bool = False,
    legacy_preset_name: str = "full_submit",
    target: str = "submit",
) -> IntentProfile:
    """Build an IntentProfile for arbitrary stage selection (compile_intent_plan applies closure)."""
    return IntentProfile(
        intent_id=intent_id,
        label=label,
        description=description,
        target=target,
        requested_stages=list(requested_stages),
        default_fetch_missing=default_fetch_missing,
        default_include_m5=default_include_m5,
        default_dry_run=default_dry_run,
        legacy_preset_name=legacy_preset_name,
    )


def build_download_cmd(config: str, subject: str) -> list[str]:
    return ["mous-pipeline", "fetch-rdr", "--config", config, "--subject", subject, "--execute"]


def build_bids_convert_cmd(config: str, subject: str) -> list[str]:
    return ["mous-pipeline", "bids-convert", "--config", config, "--subject", subject]


def build_bids_validate_cmd(root: str, subject: str) -> list[str]:
    return ["mous-pipeline", "bids-validate", "--root", root, "--subject", subject, "--verbose"]


def build_group_cmd(
    *,
    derivatives_root: str,
    subjects: list[str] | None = None,
    quarto_only: bool = False,
    use_cache: bool = False,
    test: str = "wilcoxon",
) -> list[str]:
    cmd = [
        "mous-pipeline",
        "group",
        "--derivatives-root",
        derivatives_root,
        "--test",
        test,
    ]
    clean_subjects = sorted({s.removeprefix("sub-") for s in (subjects or []) if s.strip()})
    if clean_subjects:
        cmd.extend(["--subjects", ",".join(clean_subjects)])
    if quarto_only or use_cache:
        cmd.append("--quarto-only")
    return cmd


def recommend_resources(
    *,
    n_subjects: int,
    partition_info: dict[str, int],
    peak_rss_gb: float,
    os_reserve_gb: float = 6.0,
) -> dict[str, str | int | float]:
    total_ram_gb = float(partition_info.get("max_node_mem_gb", 0))
    n_cpus = int(partition_info.get("max_node_cpus", 1))
    rec = recommend_subject_parallelism(
        total_ram_gb=total_ram_gb,
        os_reserve_gb=os_reserve_gb,
        peak_rss_gb=peak_rss_gb,
        n_cpus=n_cpus,
    )
    suggested_parallel_subjects = max(1, min(max(1, n_subjects), int(rec["n_subjects_max_conservative"]) or 1))
    cpus_per_task = max(1, int(rec["suggested_omp_num_threads_per_process"]))
    mem_per_subject_gb = max(1, int(round(max(1.0, peak_rss_gb) * 1.25)))
    total_mem_gb = min(int(total_ram_gb), max(mem_per_subject_gb, mem_per_subject_gb * suggested_parallel_subjects))
    return {
        "partition": str(partition_info.get("partition", "")),
        "suggested_parallel_subjects": suggested_parallel_subjects,
        "suggested_cpus_per_task": str(cpus_per_task),
        "suggested_mem": f"{total_mem_gb}G",
        "suggested_time": "24:00:00" if suggested_parallel_subjects > 1 else "12:00:00",
        "peak_rss_gb": peak_rss_gb,
    }


def build_recon_submit_cmd(
    *,
    config: str,
    subjects: list[str],
    account: str,
    partition: str,
    time_limit: str,
    mem: str,
    cpus_per_task: str,
    dry_run: bool = False,
) -> list[str]:
    cmd = [
        "scripts/palmetto_recon_all.sh",
        "--config",
        config,
        "--subjects",
        ",".join(subjects),
        "--partition",
        partition,
        "--account",
        account,
        "--time",
        time_limit,
        "--mem",
        mem,
        "--cpus-per-task",
        cpus_per_task,
    ]
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def build_bem_submit_cmd(
    *,
    config: str,
    subjects: list[str],
    account: str,
    partition: str,
    time_limit: str,
    mem: str,
    cpus_per_task: str,
    dependency: str = "",
    dry_run: bool = False,
) -> list[str]:
    cmd = [
        "scripts/palmetto_prep_bem.sh",
        "--config",
        config,
        "--subjects",
        ",".join(subjects),
        "--partition",
        partition,
        "--account",
        account,
        "--time",
        time_limit,
        "--mem",
        mem,
        "--cpus-per-task",
        cpus_per_task,
    ]
    if dependency:
        cmd.extend(["--dependency", dependency])
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def run_cmd(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True, cwd=str(cwd) if cwd else None)


def parse_sbatch_job_id(text: str) -> str:
    m = re.search(r"Submitted batch job (\d+)", text or "")
    return m.group(1) if m else ""


def submit_sbatch(script_path: str) -> JobRecord:
    proc = run_cmd(["sbatch", script_path])
    out = proc.stdout.strip()
    job_id = parse_sbatch_job_id(out)
    return JobRecord(
        job_id=job_id or "unknown",
        job_name="mous_driver",
        kind="driver",
        config_path="configs/palmetto_hpcnirc_fmri.yaml",
        subjects=[],
        status="SUBMITTED" if job_id else "UNKNOWN",
    )


def execute_submit_cmd(
    cmd: list[str],
    *,
    config_path: str,
    subjects: list[str],
    kind: str = "palmetto_submit",
    job_name: str = "mous_fmriprep",
) -> tuple[JobRecord | None, subprocess.CompletedProcess[str]]:
    original_cwd = Path.cwd()
    root = resolve_repo_root(config_path=config_path)
    proc = run_cmd(prepare_repo_command(cmd, root, original_cwd=original_cwd), cwd=root)
    job_id = parse_sbatch_job_id((proc.stdout or "") + "\n" + (proc.stderr or ""))
    if not job_id:
        return None, proc
    return (
        JobRecord(
            job_id=job_id,
            job_name=job_name,
            kind=kind,
            config_path=config_path,
            subjects=subjects,
            status="SUBMITTED",
        ),
        proc,
    )


def submit_detached_driver(
    submit_cmd: list[str],
    *,
    config_path: str,
    subjects: list[str],
    account: str,
    partition: str,
    time_limit: str,
    mem: str,
    cpus_per_task: str,
    venv_path: str,
    derivatives_root: str,
    repo_root: Path | None = None,
) -> tuple[JobRecord | None, subprocess.CompletedProcess[str]]:
    original_cwd = Path.cwd()
    root = resolve_repo_root(repo_root=repo_root, config_path=config_path)
    slurm_dir = Path(derivatives_root).expanduser().resolve() / "slurm"
    slurm_dir.mkdir(parents=True, exist_ok=True)
    anchored_submit_cmd = prepare_repo_command(submit_cmd, root, original_cwd=original_cwd)
    wrapped = (
        f"cd {shlex.quote(str(root))} && "
        f"source {shlex.quote(str(Path(venv_path).expanduser() / 'bin/activate'))} && "
        + " ".join(shlex.quote(part) for part in anchored_submit_cmd)
    )
    sbatch_cmd = [
        "sbatch",
        "--job-name",
        "mous_driver",
        "--partition",
        partition,
        "--account",
        account,
        "--time",
        time_limit,
        "--mem",
        mem,
        "--cpus-per-task",
        cpus_per_task,
        "--output",
        str(slurm_dir / "mous_driver_%j.out"),
        "--error",
        str(slurm_dir / "mous_driver_%j.err"),
        "--wrap",
        wrapped,
    ]
    proc = run_cmd(sbatch_cmd, cwd=root)
    job_id = parse_sbatch_job_id((proc.stdout or "") + "\n" + (proc.stderr or ""))
    if not job_id:
        return None, proc
    return (
        JobRecord(
            job_id=job_id,
            job_name="mous_driver",
            kind="detached_driver",
            config_path=config_path,
            subjects=subjects,
            status="SUBMITTED",
        ),
        proc,
    )


def submit_detached_wrap(
    wrapped_cmd: list[str],
    *,
    job_name: str,
    kind: str,
    config_path: str,
    subjects: list[str],
    account: str,
    partition: str,
    time_limit: str,
    mem: str,
    cpus_per_task: str,
    derivatives_root: str,
    repo_root: Path | None = None,
) -> tuple[JobRecord | None, subprocess.CompletedProcess[str]]:
    original_cwd = Path.cwd()
    root = resolve_repo_root(repo_root=repo_root, config_path=config_path)
    slurm_dir = Path(derivatives_root).expanduser().resolve() / "slurm"
    slurm_dir.mkdir(parents=True, exist_ok=True)
    anchored_wrapped_cmd = prepare_repo_command(wrapped_cmd, root, original_cwd=original_cwd)
    wrapped = f"cd {shlex.quote(str(root))} && " + " ".join(shlex.quote(part) for part in anchored_wrapped_cmd)
    sbatch_cmd = [
        "sbatch",
        "--job-name",
        job_name,
        "--partition",
        partition,
        "--account",
        account,
        "--time",
        time_limit,
        "--mem",
        mem,
        "--cpus-per-task",
        cpus_per_task,
        "--output",
        str(slurm_dir / f"{job_name}_%j.out"),
        "--error",
        str(slurm_dir / f"{job_name}_%j.err"),
        "--wrap",
        wrapped,
    ]
    proc = run_cmd(sbatch_cmd, cwd=root)
    job_id = parse_sbatch_job_id((proc.stdout or "") + "\n" + (proc.stderr or ""))
    if not job_id:
        return None, proc
    return (
        JobRecord(
            job_id=job_id,
            job_name=job_name,
            kind=kind,
            config_path=config_path,
            subjects=subjects,
            status="SUBMITTED",
        ),
        proc,
    )
