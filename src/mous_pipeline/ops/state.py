from __future__ import annotations

import json
from pathlib import Path

from .models import JobRecord, OpsState, SubjectSet, WorkflowPreset


def default_presets() -> dict[str, WorkflowPreset]:
    return {
        "download_only": WorkflowPreset(
            name="download_only",
            description="Download subjects from RDR only",
            mode="download",
            fetch_missing=True,
        ),
        "bids_convert_validate": WorkflowPreset(
            name="bids_convert_validate",
            description="Run bids-convert then bids-validate for selected subjects",
            mode="bids",
            bids_convert=True,
            bids_validate=True,
        ),
        "dry_run_submit": WorkflowPreset(
            name="dry_run_submit",
            description="Preview submit commands only",
            mode="submit",
            dry_run=True,
        ),
        "full_submit": WorkflowPreset(
            name="full_submit",
            description="Multimodal driver: MEG trial/group outputs + detached fMRI preprocessing (m5 skipped)",
            mode="submit",
            fetch_missing=False,
            dry_run=False,
        ),
        "m5_enabled_submit": WorkflowPreset(
            name="m5_enabled_submit",
            description="Multimodal driver including anatomical source models (m5) + detached fMRI preprocessing",
            mode="submit",
            include_m5=True,
            dry_run=False,
        ),
        "fmriprep_only_submit": WorkflowPreset(
            name="fmriprep_only_submit",
            description="fMRI preprocessing track only (detached fMRIPrep array via palmetto wrapper)",
            mode="submit",
            dry_run=False,
            extra_args=["--subjects"],
        ),
    }


def state_file_path() -> Path:
    return Path("~/.config/mous_ops/state.json").expanduser()


def load_state(path: Path | None = None) -> OpsState:
    p = path or state_file_path()
    if not p.exists():
        st = OpsState()
        st.workflow_presets = default_presets()
        return st
    payload = json.loads(p.read_text())
    st = OpsState(
        last_config=payload.get("last_config", "configs/palmetto_hpcnirc_fmri.yaml"),
        recent_configs=list(payload.get("recent_configs", [])),
        defaults=payload.get("defaults", OpsState().defaults),
        env_profile=payload.get("env_profile", {}),
        run_overrides_defaults=payload.get("run_overrides_defaults", {}),
    )
    # Migrate old bool-valued run override defaults to tri-state string values.
    migrated: dict[str, str] = {}
    for key, value in st.run_overrides_defaults.items():
        if isinstance(value, bool):
            migrated[key] = "yes" if value else "preset"
        elif isinstance(value, str) and value in {"preset", "yes", "no"}:
            migrated[key] = value
    st.run_overrides_defaults = migrated
    if not st.recent_configs:
        st.recent_configs = [st.last_config]
    elif st.last_config and st.last_config not in st.recent_configs:
        st.recent_configs.insert(0, st.last_config)
    st.recent_configs = st.recent_configs[:10]
    st.subject_sets = {
        k: SubjectSet(**v) for k, v in payload.get("subject_sets", {}).items()
    }
    raw_presets = payload.get("workflow_presets", {})
    if raw_presets:
        st.workflow_presets = {k: WorkflowPreset(**v) for k, v in raw_presets.items()}
    else:
        st.workflow_presets = default_presets()
    st.recent_jobs = [JobRecord(**r) for r in payload.get("recent_jobs", [])]
    return st


def save_state(state: OpsState, path: Path | None = None) -> None:
    p = path or state_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state.to_dict(), indent=2))
