from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SubjectSet:
    name: str
    subjects: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now_iso)


@dataclass
class WorkflowPreset:
    name: str
    description: str
    mode: str
    include_m5: bool = False
    fetch_missing: bool = False
    dry_run: bool = False
    bids_convert: bool = False
    bids_validate: bool = False
    submit_driver: bool = False
    extra_args: list[str] = field(default_factory=list)


@dataclass
class JobRecord:
    job_id: str
    job_name: str
    kind: str
    config_path: str
    subjects: list[str]
    submitted_at: str = field(default_factory=_utc_now_iso)
    status: str = "UNKNOWN"
    driver_log_out: str = ""
    driver_log_err: str = ""


@dataclass
class OpsState:
    last_config: str = "configs/palmetto_hpcnirc_fmri.yaml"
    defaults: dict[str, str] = field(
        default_factory=lambda: {
            "account": "",
            "partition": "hpcnirc",
            "mem": "256G",
            "time": "12:00:00",
            "cpus_per_task": "8",
            "venv_path": "~/.venvs/mous-palmetto",
        }
    )
    subject_sets: dict[str, SubjectSet] = field(default_factory=dict)
    workflow_presets: dict[str, WorkflowPreset] = field(default_factory=dict)
    recent_jobs: list[JobRecord] = field(default_factory=list)
    env_profile: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "last_config": self.last_config,
            "defaults": self.defaults,
            "subject_sets": {k: asdict(v) for k, v in self.subject_sets.items()},
            "workflow_presets": {k: asdict(v) for k, v in self.workflow_presets.items()},
            "recent_jobs": [asdict(j) for j in self.recent_jobs],
            "env_profile": self.env_profile,
        }
