from __future__ import annotations

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    SelectionList,
    Static,
    TabbedContent,
    TabPane,
)

from .actions import (
    build_bids_convert_cmd,
    build_bids_validate_cmd,
    build_download_cmd,
    build_submit_cmd,
    discover_subjects,
    run_cmd,
    submit_sbatch,
)
from .env import run_env_preflight
from .models import SubjectSet, WorkflowPreset
from .monitor import classify_failure, latest_log, recent_jobs, tail_text
from .state import load_state, save_state


class OpsApp(App[None]):
    TITLE = "MOUS Ops"

    def __init__(self) -> None:
        super().__init__()
        self.state = load_state()
        self.selected_subjects: list[str] = []
        self.current_preset: str = "full_submit"

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Env", id="env"):
                yield Static(id="env_status")
                yield Button("Refresh Env", id="env_refresh")
            with TabPane("Subjects", id="subjects"):
                with Vertical():
                    yield Input(value=self.state.last_config, placeholder="Config path", id="config_input")
                    yield Input(
                        value=self.state.defaults.get("data_root", "/scratch/jonathanwade/mous_data"),
                        placeholder="Data root",
                        id="data_root_input",
                    )
                    with Horizontal():
                        yield Button("Load Subjects", id="load_subjects")
                        yield Button("Save Subject Set", id="save_set")
                        yield Button("Load Subject Set", id="load_set")
                    yield SelectionList[str](id="subject_list")
                    yield Input(placeholder="Subject set name", id="set_name")
                    yield Select(
                        [(name, name) for name in sorted(self.state.subject_sets.keys())] or [("none", "none")],
                        id="set_select",
                    )
            with TabPane("Workflows", id="workflows"):
                yield Select(
                    [(name, name) for name in sorted(self.state.workflow_presets.keys())],
                    value=self.current_preset,
                    id="preset_select",
                )
                yield Input(
                    placeholder="Manual extra args (space-separated), e.g. --fetch-missing --dry-run",
                    id="manual_args_input",
                )
                yield Input(placeholder="Save manual preset as name", id="preset_name_input")
                yield Input(value=self.state.defaults.get("account", ""), placeholder="Account", id="account_input")
                yield Input(
                    value=self.state.defaults.get("partition", "hpcnirc"),
                    placeholder="Partition",
                    id="partition_input",
                )
                yield Input(value=self.state.defaults.get("time", "12:00:00"), placeholder="Time", id="time_input")
                yield Input(value=self.state.defaults.get("mem", "256G"), placeholder="Mem", id="mem_input")
                yield Input(value=self.state.defaults.get("cpus_per_task", "8"), placeholder="CPUs", id="cpus_input")
                with Horizontal():
                    yield Button("Preview Plan", id="preview_plan")
                    yield Button("Run Preset", id="run_preset")
                    yield Button("Save Preset", id="save_preset")
                    yield Button("Submit Driver", id="submit_driver")
                yield Static(id="plan_output")
            with TabPane("Monitor", id="monitor"):
                with Horizontal():
                    yield Button("Refresh Jobs", id="refresh_jobs")
                    yield Button("Analyze Latest Logs", id="analyze_logs")
                yield DataTable(id="jobs_table")
                yield Input(placeholder="Job ID for quick filter", id="job_filter")
                yield Static(id="monitor_output")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_env()
        self._refresh_subjects()
        self._refresh_jobs()

    def _refresh_env(self) -> None:
        checks = run_env_preflight(self.state.defaults.get("venv_path", "~/.venvs/mous-palmetto"))
        lines = []
        for c in checks:
            status = "OK" if c.ok else ("WARN" if not c.required else "MISSING")
            lines.append(f"{status:8} {c.name:12} {c.detail}")
        self.query_one("#env_status", Static).update("\n".join(lines))

    def _refresh_subjects(self) -> None:
        cfg = self.query_one("#config_input", Input).value.strip()
        data_root = self.query_one("#data_root_input", Input).value.strip()
        subjects = discover_subjects(cfg, data_root=data_root)
        sl = self.query_one("#subject_list", SelectionList)
        sl.clear_options()
        for s in subjects:
            sl.add_option((s, s, s in self.selected_subjects))

    def _refresh_jobs(self) -> None:
        table = self.query_one("#jobs_table", DataTable)
        table.clear(columns=True)
        table.add_columns("JobID", "Name", "State", "ExitCode", "Elapsed")
        for j in recent_jobs(hours=24):
            table.add_row(j.job_id, j.name, j.state, j.exit_code, j.elapsed)

    def _selected_subject_values(self) -> list[str]:
        sl = self.query_one("#subject_list", SelectionList)
        values = [v for v in sl.selected if isinstance(v, str)]
        self.selected_subjects = values
        return values

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "env_refresh":
            self._refresh_env()
            return
        if bid == "load_subjects":
            self._refresh_subjects()
            return
        if bid == "save_set":
            name = self.query_one("#set_name", Input).value.strip()
            if name:
                self.state.subject_sets[name] = SubjectSet(name=name, subjects=self._selected_subject_values())
                save_state(self.state)
                self.notify(f"Saved set '{name}'")
            return
        if bid == "load_set":
            select = self.query_one("#set_select", Select)
            value = str(select.value)
            if value in self.state.subject_sets:
                self.selected_subjects = self.state.subject_sets[value].subjects
                self._refresh_subjects()
            return
        if bid in {"preview_plan", "run_preset"}:
            self._run_or_preview(execute=(bid == "run_preset"))
            return
        if bid == "save_preset":
            self._save_preset_from_ui()
            return
        if bid == "submit_driver":
            job = submit_sbatch("scripts/run_mous_driver.sbatch")
            self.state.recent_jobs.insert(0, job)
            self.state.recent_jobs = self.state.recent_jobs[:40]
            save_state(self.state)
            self.notify(f"Submitted driver job {job.job_id}")
            self._refresh_jobs()
            return
        if bid == "refresh_jobs":
            self._refresh_jobs()
            return
        if bid == "analyze_logs":
            self._analyze_logs()
            return

    def _save_preset_from_ui(self) -> None:
        name = self.query_one("#preset_name_input", Input).value.strip()
        if not name:
            self.notify("Preset name required")
            return
        manual = self.query_one("#manual_args_input", Input).value.strip()
        tokens = [t for t in manual.split(" ") if t]
        preset = WorkflowPreset(
            name=name,
            description="user saved preset",
            mode="submit",
            fetch_missing="--fetch-missing" in tokens,
            dry_run="--dry-run" in tokens,
            include_m5="--include-m5" in tokens,
            extra_args=[t for t in tokens if t not in {"--fetch-missing", "--dry-run", "--include-m5"}],
        )
        self.state.workflow_presets[name] = preset
        save_state(self.state)
        sel = self.query_one("#preset_select", Select)
        sel.set_options([(k, k) for k in sorted(self.state.workflow_presets.keys())])
        self.notify(f"Saved preset '{name}'")

    def _run_or_preview(self, *, execute: bool) -> None:
        preset_name = str(self.query_one("#preset_select", Select).value)
        preset = self.state.workflow_presets.get(preset_name, WorkflowPreset(name="full_submit", description="", mode="submit"))
        subjects = self._selected_subject_values()
        cfg = self.query_one("#config_input", Input).value.strip()
        account = self.query_one("#account_input", Input).value.strip()
        partition = self.query_one("#partition_input", Input).value.strip()
        time_limit = self.query_one("#time_input", Input).value.strip()
        mem = self.query_one("#mem_input", Input).value.strip()
        cpus = self.query_one("#cpus_input", Input).value.strip()
        out = {"preset": preset.name, "subjects": subjects, "commands": []}
        for subject in subjects:
            if preset.mode == "download":
                out["commands"].append(build_download_cmd(cfg, subject))
            elif preset.mode == "bids":
                if preset.bids_convert:
                    out["commands"].append(build_bids_convert_cmd(cfg, subject))
                if preset.bids_validate:
                    root = self.query_one("#data_root_input", Input).value.strip()
                    out["commands"].append(build_bids_validate_cmd(root, subject))
            else:
                out["commands"] = [
                    build_submit_cmd(
                        preset,
                        config=cfg,
                        subjects=subjects,
                        account=account,
                        partition=partition,
                        time_limit=time_limit,
                        mem=mem,
                        cpus_per_task=cpus,
                    )
                ]
                break
        if execute:
            logs = []
            for cmd in out["commands"]:
                proc = run_cmd(cmd, cwd=Path.cwd())
                logs.append(
                    {
                        "cmd": cmd,
                        "returncode": proc.returncode,
                        "stdout": proc.stdout[-5000:],
                        "stderr": proc.stderr[-5000:],
                    }
                )
            out["results"] = logs
        self.query_one("#plan_output", Static).update(json.dumps(out, indent=2))

    def _analyze_logs(self) -> None:
        slurm_dir = Path("/scratch/jonathanwade/mous_derivatives/slurm")
        driver_err = latest_log(slurm_dir, "mous_driver_*.err")
        fmri_err = latest_log(slurm_dir, "fmriprep_*.err")
        chunks = []
        for label, path in (("driver_err", driver_err), ("fmriprep_err", fmri_err)):
            if path is None:
                chunks.append(f"[{label}] none found")
                continue
            text = tail_text(path, lines=120)
            kind = classify_failure(text)
            chunks.append(f"[{label}] {path}\nclassification={kind}\n{text}\n")
        self.query_one("#monitor_output", Static).update("\n\n".join(chunks))


def run_ops_app() -> None:
    OpsApp().run()
