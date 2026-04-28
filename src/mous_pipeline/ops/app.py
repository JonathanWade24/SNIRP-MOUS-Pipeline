from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    SelectionList,
    Static,
)

from .actions import (
    compute_undownloaded_subjects,
    discover_remote_subjects,
    build_bids_convert_cmd,
    build_bids_validate_cmd,
    build_download_cmd,
    build_submit_cmd,
    discover_subjects,
    run_cmd,
    submit_detached_driver,
    submit_detached_wrap,
)
from .env import run_env_preflight
from .models import SubjectSet, WorkflowPreset
from .monitor import classify_failure, latest_log, recent_jobs, squeue_jobs, tail_text
from .state import load_state, save_state


# ── CSS ──────────────────────────────────────────────────────────────────────

APP_CSS = """
/* ── Shared ─────────────────────────────────────────── */
Screen { background: $background; }

.wizard-header {
    background: $primary-darken-2;
    color: $text;
    text-style: bold;
    height: 3;
    padding: 0 2;
    content-align: left middle;
    width: 100%;
}

.section-title {
    background: $primary-darken-3;
    color: $text-muted;
    text-style: bold;
    height: 1;
    padding: 0 1;
    width: 100%;
}

.frow {
    height: 3;
    align: left middle;
    padding: 0 2;
    margin-bottom: 0;
}

.flabel {
    width: 14;
    content-align: right middle;
    padding: 0 1 0 0;
    color: $text-muted;
}

.nav-bar {
    height: 3;
    align: center middle;
    padding: 0 2;
    margin-top: 1;
    border-top: solid $primary-darken-3;
}

Button { margin: 0 1; }

/* ── Dashboard ───────────────────────────────────────── */
#greeting {
    border: heavy $accent;
    background: $boost;
    padding: 1 2;
    margin: 1 2 0 2;
    height: 5;
}
#greeting-title { text-style: bold; }
#greeting-sub   { color: $text-muted; }

#env-bar {
    height: 1;
    background: $surface;
    padding: 0 2;
    margin: 0 2 1 2;
}

.jobs-panel {
    border: round $primary-darken-2;
    margin: 0 2 1 2;
    height: 10;
}
.jobs-panel.tall { height: 13; }

#dash-actions {
    height: 3;
    align: center middle;
    margin: 0 2 1 2;
}

/* ── Subjects ────────────────────────────────────────── */
#subject-list {
    border: round $accent;
    height: 13;
    margin: 0 2;
}
#cfg-input, #data-root-input { width: 1fr; }

/* ── Preset ──────────────────────────────────────────── */
#preset-select { margin: 1 2; }
#preset-desc {
    border: round $primary-darken-2;
    background: $surface;
    height: 5;
    padding: 1;
    margin: 0 2;
    color: $text-muted;
}

/* ── Resources ───────────────────────────────────────── */
#account-input  { width: 26; }
#partition-input, #time-input, #mem-input, #cpus-input { width: 14; }
#cmd-preview {
    border: round $success;
    background: $surface;
    padding: 1;
    margin: 0 2;
    height: 8;
    overflow-y: auto;
    overflow-x: auto;
}

/* ── Log viewer ──────────────────────────────────────── */
#log-path-input { width: 1fr; }
#failure-banner {
    height: 3;
    margin: 0 2;
    border: round $warning;
    padding: 0 1;
    content-align: left middle;
}
#log-output { border: round $primary-darken-2; margin: 0 2; height: 1fr; }
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_squeue() -> list:
    try:
        return squeue_jobs()
    except Exception:
        return []


def _safe_sacct() -> list:
    try:
        return recent_jobs(hours=24)
    except Exception:
        return []


def _greeting_text(active: list, tracked: list) -> tuple[str, str]:
    """Return (Rich headline, Rich subtitle) for the dashboard banner."""
    mous = [j for j in active if "mous" in j.name.lower()]
    if mous:
        n = len(mous)
        names = "  ·  ".join(dict.fromkeys(j.name for j in mous[:3]))
        return (
            f"[bold green]⚡  {n} MOUS job{'s' if n > 1 else ''} currently running[/bold green]",
            f"[dim]{names}[/dim]\n"
            "Want to queue another run, or tail the logs?  [bold]N[/bold] new run  [bold]L[/bold] logs",
        )

    failed = [j for j in tracked[:5] if j.status in {"FAILED", "TIMEOUT", "OUT_OF_MEMORY"}]
    if failed:
        last = failed[0]
        subs = last.subjects[0] if last.subjects else "-"
        return (
            f"[bold red]✗  Last tracked run failed ({last.status})[/bold red]",
            f"[dim]{last.job_name}  ·  sub-{subs}  ·  {last.submitted_at[:10]}[/dim]\n"
            "Press [bold]L[/bold] to tail the log, or [bold]N[/bold] to retry with updated resources.",
        )

    if tracked:
        last = tracked[0]
        return (
            f"[bold green]✓  Last tracked run: {last.status}[/bold green]",
            f"[dim]{last.job_name}  ·  {last.submitted_at[:10]}[/dim]\n"
            "Ready for another?  Press [bold]N[/bold] to start a new run.",
        )

    return (
        "[bold]Welcome to MOUS Ops[/bold]",
        "No tracked runs yet.\nPress [bold]N[/bold] to submit your first run.",
    )


def _latest_manifest_for_subject(derivatives_root: str, subject: str) -> Path | None:
    base = Path(derivatives_root).expanduser() / f"sub-{subject}" / "m9_orchestration"
    if not base.exists():
        return None
    manifests = sorted(base.glob("*_run_manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return manifests[0] if manifests else None


PRESET_DESCRIPTIONS: dict[str, str] = {
    "download_only":          "Download subject data from RDR only. No processing.",
    "bids_convert_validate":  "Run BIDS conversion + mne_bids validation. Good first step before submit.",
    "dry_run_submit":         "Preview palmetto_submit.sh commands without running anything. Safe to use anytime.",
    "full_submit":            "Multimodal driver: MEG trial metrics + MEG group summaries; submits fMRI preprocessing array; skips anatomical source models (m5).",
    "m5_enabled_submit":      "Multimodal driver including anatomical source models (m5) before subject MEG outputs; also submits fMRI preprocessing array.",
    "fmriprep_only_submit":   "Submit fMRI preprocessing track for selected subjects.",
}

PRESET_LABELS: dict[str, str] = {
    "download_only": "Download Only",
    "bids_convert_validate": "BIDS Convert + Validate",
    "dry_run_submit": "Dry Run (No Submit)",
    "full_submit": "Multimodal Driver (MEG + fMRI preprocess)",
    "m5_enabled_submit": "Multimodal Driver + Anatomical Source Models (m5)",
    "fmriprep_only_submit": "fMRI Preprocessing Only",
}


def _preset_what_runs(name: str) -> str:
    if name == "download_only":
        return "Runs: RDR download only."
    if name == "bids_convert_validate":
        return "Runs: BIDS convert + validate only."
    if name == "dry_run_submit":
        return "Runs: command preview only; no jobs submitted."
    if name == "fmriprep_only_submit":
        return "Runs: fMRI preprocessing track. This submits detached fMRIPrep array jobs."
    if name == "m5_enabled_submit":
        return "Runs: Anatomical Source Models (m5), subject-level MEG outputs, MEG group summaries, and detached fMRI preprocessing."
    return "Runs: subject-level MEG outputs, MEG group summaries, and detached fMRI preprocessing."

FAILURE_HINTS: dict[str, str] = {
    "oom":         "[bold red]OUT OF MEMORY[/bold red]  →  Increase --mem (try 512G or 1T)",
    "timeout":     "[bold yellow]TIMEOUT[/bold yellow]  →  Increase --time (try 24:00:00 or 48:00:00)",
    "validation":  "[bold yellow]BIDS VALIDATION[/bold yellow]  →  Run bids-convert, or set skip_bids_validation: true",
    "missing_file":"[bold yellow]MISSING FILE[/bold yellow]  →  Check data_root paths and repocli fetch",
    "container":   "[bold red]CONTAINER ERROR[/bold red]  →  Verify fmriprep_container path and apptainer bind mounts",
    "permission":  "[bold red]PERMISSION DENIED[/bold red]  →  Check scratch/project directory permissions",
    "unknown":     "[dim]No pattern matched. Scan the log manually.[/dim]",
}


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardScreen(Screen):
    BINDINGS = [
        Binding("n", "new_run",   "New Run"),
        Binding("d", "redownload", "Re-download"),
        Binding("j", "run_results", "Runs"),
        Binding("l", "view_logs", "Logs"),
        Binding("r", "refresh",   "Refresh"),
        Binding("q", "quit_app",  "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        yield Static("", id="env-bar")

        with Container(id="greeting"):
            yield Static("", id="greeting-title")
            yield Static("", id="greeting-sub")

        with Horizontal(id="dash-actions"):
            yield Button("▶  New Run",     id="btn-new-run",  variant="success")
            yield Button("⤓  Re-download", id="btn-redownload", variant="warning")
            yield Button("🗂  Run Results", id="btn-runs", variant="default")
            yield Button("📋  View Logs",   id="btn-logs",     variant="default")
            yield Button("⟳  Refresh",     id="btn-refresh",  variant="default")

        with Container(classes="jobs-panel tall"):
            yield Label("⚡  Active SLURM Jobs  (mous_*)", classes="section-title")
            yield DataTable(id="active-table", show_cursor=False)

        with Container(classes="jobs-panel"):
            yield Label("🕒  Recently Tracked Jobs", classes="section-title")
            yield DataTable(id="recent-table", show_cursor=False)

        yield Footer()

    def on_mount(self) -> None:
        self._setup_tables()
        self._refresh_all()

    def _setup_tables(self) -> None:
        at = self.query_one("#active-table", DataTable)
        at.add_columns("Job ID", "Name", "State", "Elapsed")

        rt = self.query_one("#recent-table", DataTable)
        rt.add_columns("Submitted", "Job ID", "Name", "Subjects", "Status")

    def _refresh_all(self) -> None:
        self._refresh_env()
        active  = _safe_squeue()
        tracked = self.app.state.recent_jobs
        self._refresh_greeting(active, tracked)
        self._refresh_active_table(active)
        self._refresh_recent_table(tracked)

    def _refresh_env(self) -> None:
        checks = run_env_preflight(self.app.state.defaults.get("venv_path", "~/.venvs/mous-palmetto"))
        parts = []
        for c in checks:
            if c.ok:
                parts.append(f"[green]{c.name} ✓[/green]")
            elif not c.required:
                parts.append(f"[yellow]{c.name} –[/yellow]")
            else:
                parts.append(f"[red bold]{c.name} ✗[/red bold]")
        self.query_one("#env-bar", Static).update("  ".join(parts))

    def _refresh_greeting(self, active: list, tracked: list) -> None:
        title, sub = _greeting_text(active, tracked)
        self.query_one("#greeting-title", Static).update(title)
        self.query_one("#greeting-sub",   Static).update(sub)

    def _refresh_active_table(self, jobs: list) -> None:
        t = self.query_one("#active-table", DataTable)
        t.clear()
        mous = [j for j in jobs if "mous" in j.name.lower()] or []
        if not mous:
            t.add_row("-", "(no active MOUS jobs)", "-", "-")
            return
        for j in mous[:12]:
            if "RUNNING" in j.state:
                state_str = f"[green]{j.state}[/green]"
            elif "PENDING" in j.state:
                state_str = f"[yellow]{j.state}[/yellow]"
            else:
                state_str = f"[red]{j.state}[/red]"
            t.add_row(j.job_id, j.name, state_str, j.elapsed)

    def _refresh_recent_table(self, jobs: list) -> None:
        t = self.query_one("#recent-table", DataTable)
        t.clear()
        if not jobs:
            t.add_row("-", "-", "(none tracked yet)", "-", "-")
            return
        for j in jobs[:8]:
            subs = ",".join(j.subjects[:3]) or "-"
            if j.status in {"COMPLETED", "SUBMITTED"}:
                status_str = f"[green]{j.status}[/green]"
            elif j.status in {"FAILED", "TIMEOUT", "OUT_OF_MEMORY"}:
                status_str = f"[red]{j.status}[/red]"
            else:
                status_str = j.status
            t.add_row(j.submitted_at[:16], j.job_id, j.job_name, subs, status_str)

    def action_new_run(self)  -> None: self.app.push_screen(SubjectsScreen())
    def action_redownload(self) -> None: self.app.push_screen(RedownloadScreen())
    def action_run_results(self) -> None: self.app.push_screen(RunResultsScreen())
    def action_view_logs(self)-> None: self.app.push_screen(LogScreen())
    def action_refresh(self)  -> None:
        self._refresh_all()
        self.notify("Refreshed")
    def action_quit_app(self) -> None: self.app.exit()

    @on(Button.Pressed, "#btn-new-run")
    def _on_new(self, _) -> None:
        self.action_new_run()

    @on(Button.Pressed, "#btn-logs")
    def _on_logs(self, _) -> None:
        self.action_view_logs()

    @on(Button.Pressed, "#btn-redownload")
    def _on_redownload(self, _) -> None:
        self.action_redownload()

    @on(Button.Pressed, "#btn-runs")
    def _on_runs(self, _) -> None:
        self.action_run_results()

    @on(Button.Pressed, "#btn-refresh")
    def _on_refresh(self, _) -> None:
        self.action_refresh()


# ── Step 1: Subjects ──────────────────────────────────────────────────────────

class SubjectsScreen(Screen):
    BINDINGS = [Binding("escape", "action_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("  New Run  ›  Step 1 / 3  ›  Select Subjects", classes="wizard-header")

        with Horizontal(classes="frow"):
            yield Label("Config:", classes="flabel")
            yield Input(value=self.app.state.last_config, id="cfg-input",
                        placeholder="configs/palmetto_hpcnirc_fmri.yaml")

        with Horizontal(classes="frow"):
            yield Label("Data root:", classes="flabel")
            yield Input(value=self.app.state.defaults.get("data_root", "/scratch/jonathanwade/mous_data"),
                        id="data-root-input", placeholder="/scratch/$USER/mous_data")

        with Horizontal(classes="frow"):
            yield Button("↺ Refresh List", id="btn-load", variant="default")
            yield Button("☁ Query RDR",    id="btn-query-rdr", variant="default")
            yield Button("✓ All",          id="btn-all",  variant="default")
            yield Button("✗ None",         id="btn-none", variant="default")

        yield SelectionList[str](id="subject-list")
        yield Label("  Undownloaded subjects (available in RDR)", classes="section-title")
        yield Static("[dim]Press 'Query RDR' to fetch remote availability.[/dim]", id="undownloaded-box")

        with Horizontal(classes="frow"):
            yield Label("Saved set:", classes="flabel")
            yield Select([], id="set-select", allow_blank=True)
            yield Button("Load", id="btn-load-set", variant="default")

        with Horizontal(classes="frow"):
            yield Label("Save as:", classes="flabel")
            yield Input(placeholder="set name…", id="set-name-input")
            yield Button("Save Set", id="btn-save-set", variant="default")

        with Horizontal(classes="nav-bar"):
            yield Button("← Back",          id="btn-back", variant="default")
            yield Button("Next: Preset →",  id="btn-next", variant="primary")

        yield Footer()

    def on_mount(self) -> None:
        self._populate_set_dropdown()
        self._load_subjects()

    def _populate_set_dropdown(self) -> None:
        names = sorted(self.app.state.subject_sets.keys())
        self.query_one("#set-select", Select).set_options(
            [(n, n) for n in names] or [("(no saved sets)", "")]
        )

    def _load_subjects(self) -> None:
        cfg       = self.query_one("#cfg-input",       Input).value.strip()
        data_root = self.query_one("#data-root-input", Input).value.strip()
        subjects  = discover_subjects(cfg, data_root=data_root or None)
        sl = self.query_one("#subject-list", SelectionList)
        sl.clear_options()
        prev = set(self.app.wizard_subjects)
        for s in subjects:
            sl.add_option((f"sub-{s}", s, s in prev))
        self._local_subjects = subjects
        if not subjects:
            self.notify("No subjects found — check config/data-root paths.", severity="warning")
        self._refresh_undownloaded_box()

    def _refresh_undownloaded_box(self) -> None:
        box = self.query_one("#undownloaded-box", Static)
        local = getattr(self, "_local_subjects", [])
        remote = getattr(self, "_remote_subjects", [])
        if not remote:
            box.update("[dim]Press 'Query RDR' to fetch remote availability.[/dim]")
            return
        missing = compute_undownloaded_subjects(local, remote)
        if not missing:
            box.update("[green]All remote subjects appear downloaded locally.[/green]")
            return
        box.update("  " + "  ·  ".join(f"sub-{s}" for s in missing))

    @on(Button.Pressed, "#btn-load")
    def _on_load(self, _) -> None:
        self._load_subjects()

    @on(Button.Pressed, "#btn-query-rdr")
    def _on_query_rdr(self, _) -> None:
        cfg = self.query_one("#cfg-input", Input).value.strip()
        remote, err = discover_remote_subjects(cfg)
        self._remote_subjects = remote
        if err:
            self.notify(err, severity="warning")
        else:
            self.notify(f"Loaded {len(remote)} remote subjects from RDR")
        self._refresh_undownloaded_box()

    @on(Button.Pressed, "#btn-all")
    def _on_all(self, _) -> None:
        self.query_one("#subject-list", SelectionList).select_all()

    @on(Button.Pressed, "#btn-none")
    def _on_none(self, _) -> None:
        self.query_one("#subject-list", SelectionList).deselect_all()

    @on(Button.Pressed, "#btn-load-set")
    def _on_load_set(self, _) -> None:
        name = str(self.query_one("#set-select", Select).value)
        if name and name in self.app.state.subject_sets:
            self.app.wizard_subjects = list(self.app.state.subject_sets[name].subjects)
            self._load_subjects()
            self.notify(f"Loaded set '{name}'")

    @on(Button.Pressed, "#btn-save-set")
    def _on_save_set(self, _) -> None:
        name = self.query_one("#set-name-input", Input).value.strip()
        if not name:
            self.notify("Enter a name first", severity="warning")
            return
        subs = list(self.query_one("#subject-list", SelectionList).selected)
        self.app.state.subject_sets[name] = SubjectSet(name=name, subjects=subs)
        save_state(self.app.state)
        self._populate_set_dropdown()
        self.notify(f"Saved '{name}' ({len(subs)} subjects)")

    @on(Button.Pressed, "#btn-back")
    def action_back(self) -> None: self.app.pop_screen()

    @on(Button.Pressed, "#btn-next")
    def _on_next(self, _) -> None:
        selected = list(self.query_one("#subject-list", SelectionList).selected)
        if not selected:
            self.notify("Select at least one subject", severity="warning")
            return
        self.app.wizard_subjects = selected
        self.app.wizard_config   = self.query_one("#cfg-input", Input).value.strip()
        self.app.state.last_config = self.app.wizard_config
        self.app.push_screen(PresetScreen())


# ── Step 2: Preset ────────────────────────────────────────────────────────────

class PresetScreen(Screen):
    BINDINGS = [Binding("escape", "action_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("  New Run  ›  Step 2 / 3  ›  Choose Workflow", classes="wizard-header")

        with Horizontal(classes="frow"):
            yield Label("Preset:", classes="flabel")
            names = sorted(self.app.state.workflow_presets.keys())
            cur   = self.app.wizard_preset_name if self.app.wizard_preset_name in names else names[0]
            yield Select([(PRESET_LABELS.get(n, n), n) for n in names], value=cur, id="preset-select")

        yield Static(
            PRESET_DESCRIPTIONS.get(self.app.wizard_preset_name, ""),
            id="preset-desc",
        )
        yield Static(
            "[dim]" + _preset_what_runs(self.app.wizard_preset_name) + "[/dim]",
            id="preset-what-runs",
        )

        yield Label("  Subjects selected for this run:", classes="section-title")
        subs = self.app.wizard_subjects
        yield Static(
            "  " + "  ·  ".join(f"sub-{s}" for s in subs) if subs else "[dim](none — go back and select subjects)[/dim]",
            id="subjects-summary",
        )

        with Horizontal(classes="nav-bar"):
            yield Button("← Back",            id="btn-back", variant="default")
            yield Button("Next: Resources →",  id="btn-next", variant="primary")

        yield Footer()

    @on(Select.Changed, "#preset-select")
    def _on_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        name = str(event.value)
        self.app.wizard_preset_name = name
        preset = self.app.state.workflow_presets.get(name)
        desc = PRESET_DESCRIPTIONS.get(name, preset.description if preset else "")
        self.query_one("#preset-desc", Static).update(desc)
        self.query_one("#preset-what-runs", Static).update("[dim]" + _preset_what_runs(name) + "[/dim]")

    @on(Button.Pressed, "#btn-back")
    def action_back(self) -> None: self.app.pop_screen()

    @on(Button.Pressed, "#btn-next")
    def _on_next(self, _) -> None:
        val = self.query_one("#preset-select", Select).value
        if val is Select.BLANK:
            self.notify("Choose a preset", severity="warning")
            return
        self.app.wizard_preset_name = str(val)
        self.app.push_screen(ResourcesScreen())


# ── Step 3: Resources + Submit ────────────────────────────────────────────────

class ResourcesScreen(Screen):
    BINDINGS = [Binding("escape", "action_back", "Back")]

    def compose(self) -> ComposeResult:
        d = self.app.state.defaults
        yield Header(show_clock=True)
        yield Static("  New Run  ›  Step 3 / 3  ›  Resources & Submit", classes="wizard-header")

        with Horizontal(classes="frow"):
            yield Label("Account:", classes="flabel")
            yield Input(value=d.get("account", ""), id="account-input", placeholder="your_slurm_account")
            yield Label("Partition:", classes="flabel")
            yield Input(value=d.get("partition", "hpcnirc"), id="partition-input")

        with Horizontal(classes="frow"):
            yield Label("Time:", classes="flabel")
            yield Input(value=d.get("time", "12:00:00"), id="time-input")
            yield Label("Mem:", classes="flabel")
            yield Input(value=d.get("mem", "256G"), id="mem-input")
            yield Label("CPUs:", classes="flabel")
            yield Input(value=d.get("cpus_per_task", "8"), id="cpus-input")

        yield Static(
            f"[dim]Preset:[/dim] [bold]{PRESET_LABELS.get(self.app.wizard_preset_name, self.app.wizard_preset_name)}[/bold]  "
            f"[dim]Subjects:[/dim] [bold]{', '.join('sub-' + s for s in self.app.wizard_subjects)}[/bold]",
            id="run-summary",
        )

        yield Static(
            "[dim]Submit launches a detached Multimodal Driver job (safe for SSH disconnects). "
            "fMRI preprocessing may continue in separate mous_fmriprep array jobs after the driver exits.[/dim]",
            id="cmd-preview",
        )

        with Horizontal(classes="nav-bar"):
            yield Button("← Back",       id="btn-back",    variant="default")
            yield Button("Preview",       id="btn-preview", variant="default")
            yield Button("🔍  Dry Run",   id="btn-dry",     variant="warning")
            yield Button("▶  Submit",     id="btn-submit",  variant="success")

        yield Footer()

    def _collect(self) -> dict:
        return dict(
            account      = self.query_one("#account-input",   Input).value.strip(),
            partition    = self.query_one("#partition-input",  Input).value.strip(),
            time_limit   = self.query_one("#time-input",       Input).value.strip(),
            mem          = self.query_one("#mem-input",         Input).value.strip(),
            cpus_per_task= self.query_one("#cpus-input",       Input).value.strip(),
        )

    def _save_defaults(self, r: dict) -> None:
        self.app.state.defaults.update({
            "account":      r["account"],
            "partition":    r["partition"],
            "time":         r["time_limit"],
            "mem":          r["mem"],
            "cpus_per_task":r["cpus_per_task"],
        })
        save_state(self.app.state)

    def _build(self, *, dry: bool = False) -> list[str]:
        preset = deepcopy(
            self.app.state.workflow_presets.get(
                self.app.wizard_preset_name,
                WorkflowPreset(name="full_submit", description="", mode="submit"),
            )
        )
        if dry:
            preset.dry_run = True
        r = self._collect()
        return build_submit_cmd(
            preset,
            config=self.app.wizard_config,
            subjects=self.app.wizard_subjects,
            **r,
        )

    @on(Button.Pressed, "#btn-back")
    def action_back(self) -> None: self.app.pop_screen()

    @on(Button.Pressed, "#btn-preview")
    def _on_preview(self, _) -> None:
        cmd = self._build()
        self.query_one("#cmd-preview", Static).update(
            "[bold]Command preview:[/bold]\n" + " ".join(cmd)
        )

    @on(Button.Pressed, "#btn-dry")
    def _on_dry(self, _) -> None:
        r = self._collect()
        self._save_defaults(r)
        cmd = self._build(dry=True)
        self.query_one("#cmd-preview", Static).update(
            "[bold yellow]Dry-run:[/bold yellow]\n" + " ".join(cmd) + "\n\n[dim]Running…[/dim]"
        )
        proc = run_cmd(cmd, cwd=Path.cwd())
        out = (proc.stdout or "") + (proc.stderr or "")
        self.query_one("#cmd-preview", Static).update(
            "[bold yellow]Dry-run output:[/bold yellow]\n" + out[-3000:]
        )
        self.notify("Dry run complete")

    @on(Button.Pressed, "#btn-submit")
    def _on_submit(self, _) -> None:
        r = self._collect()
        if not r["account"]:
            self.notify("Account is required before submitting", severity="error")
            return
        self._save_defaults(r)
        cmd = self._build()
        self.query_one("#cmd-preview", Static).update(
            "[bold]Submitting detached driver:[/bold]\n" + " ".join(cmd) + "\n\n[dim]Submitting via sbatch --wrap…[/dim]"
        )
        job, proc = submit_detached_driver(
            cmd,
            config_path=self.app.wizard_config,
            subjects=self.app.wizard_subjects,
            account=r["account"],
            partition=r["partition"],
            time_limit=r["time_limit"],
            mem=r["mem"],
            cpus_per_task=r["cpus_per_task"],
            venv_path=self.app.state.defaults.get("venv_path", "~/.venvs/mous-palmetto"),
            derivatives_root=self.app.state.defaults.get("derivatives_root", "/scratch/jonathanwade/mous_derivatives"),
            repo_root=Path.cwd(),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            self.notify(f"Submit failed (rc={proc.returncode})", severity="error")
            self.query_one("#cmd-preview", Static).update(
                "[bold red]Submit error:[/bold red]\n" + out[-3000:]
            )
            return
        if job:
            self.app.state.recent_jobs.insert(0, job)
            self.app.state.recent_jobs = self.app.state.recent_jobs[:40]
            save_state(self.app.state)
            self.notify(f"✓  Submitted — Job ID {job.job_id}")
        else:
            self.notify("Submitted (no job ID captured)")
        self.query_one("#cmd-preview", Static).update(
            "[bold green]Submitted:[/bold green]\n" + out[-3000:]
        )


class RedownloadScreen(Screen):
    BINDINGS = [Binding("escape", "action_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("  Re-download Subject  ›  RDR Fetch", classes="wizard-header")
        with Horizontal(classes="frow"):
            yield Label("Config:", classes="flabel")
            yield Input(value=self.app.state.last_config, id="rd-config-input")
        with Horizontal(classes="frow"):
            yield Label("Subject:", classes="flabel")
            yield Input(placeholder="A2003", id="rd-subject-input")
        with Horizontal(classes="frow"):
            yield Label("", classes="flabel")
            yield Button("Preview", id="rd-preview", variant="default")
            yield Button("Execute re-download", id="rd-exec", variant="warning")
        yield Static("", id="rd-output")
        with Horizontal(classes="nav-bar"):
            yield Button("← Back", id="rd-back", variant="default")
        yield Footer()

    @on(Button.Pressed, "#rd-preview")
    def _preview(self, _) -> None:
        cfg = self.query_one("#rd-config-input", Input).value.strip()
        subject = self.query_one("#rd-subject-input", Input).value.strip().removeprefix("sub-")
        if not subject:
            self.notify("Enter a subject ID", severity="warning")
            return
        cmd = build_download_cmd(cfg, subject)
        self.query_one("#rd-output", Static).update("[bold]Will run:[/bold]\n" + " ".join(cmd))

    @on(Button.Pressed, "#rd-exec")
    def _execute(self, _) -> None:
        cfg = self.query_one("#rd-config-input", Input).value.strip()
        subject = self.query_one("#rd-subject-input", Input).value.strip().removeprefix("sub-")
        if not subject:
            self.notify("Enter a subject ID", severity="warning")
            return
        account = self.app.state.defaults.get("account", "").strip()
        if not account:
            self.notify("Set default account first (use New Run resources screen)", severity="error")
            return
        cmd = build_download_cmd(cfg, subject)
        proc_job, proc = submit_detached_wrap(
            cmd,
            job_name="mous_fetch_rdr",
            kind="rdr_fetch",
            config_path=cfg,
            subjects=[subject],
            account=account,
            partition=self.app.state.defaults.get("partition", "hpcnirc"),
            time_limit=self.app.state.defaults.get("fetch_time", "02:00:00"),
            mem=self.app.state.defaults.get("fetch_mem", "16G"),
            cpus_per_task=self.app.state.defaults.get("fetch_cpus_per_task", "1"),
            derivatives_root=self.app.state.defaults.get("derivatives_root", "/scratch/jonathanwade/mous_derivatives"),
            repo_root=Path.cwd(),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            self.query_one("#rd-output", Static).update(f"[bold red]Failed rc={proc.returncode}[/bold red]\n" + out[-4000:])
            return
        if proc_job:
            self.app.state.recent_jobs.insert(0, proc_job)
            self.app.state.recent_jobs = self.app.state.recent_jobs[:40]
            save_state(self.app.state)
            tag = f"[bold green]Submitted detached fetch job {proc_job.job_id}[/bold green]"
        else:
            tag = "[bold yellow]Submitted (job id not parsed)[/bold yellow]"
        self.query_one("#rd-output", Static).update(f"{tag}\n" + out[-4000:])

    @on(Button.Pressed, "#rd-back")
    def action_back(self) -> None:
        self.app.pop_screen()


class RunResultsScreen(Screen):
    BINDINGS = [Binding("escape", "action_back", "Back"), Binding("r", "refresh_rows", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("  Run Browser  ›  Logs + Results", classes="wizard-header")
        yield DataTable(id="runs-table")
        with Horizontal(classes="frow"):
            yield Button("Open driver log", id="runs-driver-log", variant="default")
            yield Button("Open fMRIPrep log", id="runs-fmri-log", variant="default")
            yield Button("Show results paths", id="runs-results", variant="primary")
        yield Static("", id="runs-output")
        with Horizontal(classes="nav-bar"):
            yield Button("← Back", id="runs-back", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#runs-table", DataTable)
        table.add_columns("Submitted", "JobID", "Kind", "Subjects", "Status")
        table.cursor_type = "row"
        self._refresh_rows()

    def _refresh_rows(self) -> None:
        table = self.query_one("#runs-table", DataTable)
        table.clear()
        for j in self.app.state.recent_jobs[:40]:
            subs = ",".join(j.subjects[:3]) or "-"
            kind = self._display_run_kind(j.kind)
            table.add_row(j.submitted_at[:16], j.job_id, kind, subs, j.status)

    def _display_run_kind(self, kind: str) -> str:
        mapping = {
            "detached_driver": "Driver Job",
            "driver": "Driver Job",
            "palmetto_submit": "fMRI Array Submit",
            "rdr_fetch": "Download Job",
            "preset:bids_convert_validate": "BIDS Job",
        }
        return mapping.get(kind, kind)

    def action_refresh_rows(self) -> None:
        self._refresh_rows()

    def _selected_job(self):
        table = self.query_one("#runs-table", DataTable)
        idx = table.cursor_row
        if idx is None or idx < 0 or idx >= len(self.app.state.recent_jobs[:40]):
            return None
        return self.app.state.recent_jobs[idx]

    @on(Button.Pressed, "#runs-driver-log")
    def _open_driver_log(self, _) -> None:
        job = self._selected_job()
        if not job:
            self.notify("Select a run row first", severity="warning")
            return
        slurm_dir = Path(self.app.state.defaults.get("derivatives_root", "/scratch/jonathanwade/mous_derivatives")).expanduser() / "slurm"
        path = slurm_dir / f"mous_driver_{job.job_id}.err"
        self.app.push_screen(LogScreen(initial_log_path=path))

    @on(Button.Pressed, "#runs-fmri-log")
    def _open_fmri_log(self, _) -> None:
        job = self._selected_job()
        if not job:
            self.notify("Select a run row first", severity="warning")
            return
        slurm_dir = Path(self.app.state.defaults.get("derivatives_root", "/scratch/jonathanwade/mous_derivatives")).expanduser() / "slurm"
        path = slurm_dir / f"fmriprep_{job.job_id}_0.err"
        self.app.push_screen(LogScreen(initial_log_path=path))

    @on(Button.Pressed, "#runs-results")
    def _show_results(self, _) -> None:
        job = self._selected_job()
        if not job:
            self.notify("Select a run row first", severity="warning")
            return
        derivatives_root = self.app.state.defaults.get("derivatives_root", "/scratch/jonathanwade/mous_derivatives")
        lines = [
            f"[bold]Job:[/bold] {job.job_id}  [bold]Type:[/bold] {self._display_run_kind(job.kind)}",
            f"[bold]Subjects:[/bold] {', '.join(job.subjects) if job.subjects else '-'}",
        ]
        if job.kind in {"driver", "detached_driver"}:
            lines.append("[dim]Note: driver jobs can complete before detached fMRI array jobs complete.[/dim]")
        for subject in job.subjects:
            manifest = _latest_manifest_for_subject(derivatives_root, subject)
            subject_root = Path(derivatives_root).expanduser() / f"sub-{subject}"
            lines.append(f"sub-{subject}: {subject_root}")
            lines.append(f"manifest: {manifest if manifest else '(not found)'}")
        self.query_one("#runs-output", Static).update("\n".join(lines))

    @on(Button.Pressed, "#runs-back")
    def action_back(self) -> None:
        self.app.pop_screen()


# ── Log Viewer ────────────────────────────────────────────────────────────────

class LogScreen(Screen):
    BINDINGS = [
        Binding("escape", "action_back", "Back"),
        Binding("r", "refresh_log",      "Refresh"),
    ]

    def __init__(self, initial_log_path: Path | None = None) -> None:
        super().__init__()
        self._initial_log_path = initial_log_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("  Log Viewer  ›  Latest SLURM Error Logs", classes="wizard-header")

        with Horizontal(classes="frow"):
            yield Label("Log file:", classes="flabel")
            yield Input(placeholder="paste path or use Auto-detect", id="log-path-input")
            yield Button("↺ Load",       id="btn-load-log",  variant="default")
            yield Button("Auto-detect",  id="btn-autodetect", variant="default")
            yield Button("Newest logs",  id="btn-refresh-recent", variant="default")

        yield Label("  Newest logs by modification time", classes="section-title")
        yield DataTable(id="recent-logs-table")
        with Horizontal(classes="frow"):
            yield Button("Load selected recent log", id="btn-load-selected", variant="primary")

        yield Static("", id="failure-banner")
        yield RichLog(id="log-output", highlight=True, markup=True, wrap=False)

        with Horizontal(classes="nav-bar"):
            yield Button("← Back", id="btn-back", variant="default")

        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#recent-logs-table", DataTable)
        table.add_columns("Type", "Updated", "File")
        table.cursor_type = "row"
        self._recent_log_paths: list[Path] = []
        self._refresh_recent_logs()
        if self._initial_log_path:
            self.query_one("#log-path-input", Input).value = str(self._initial_log_path)
            self._load_log(self._initial_log_path)
        else:
            self._autodetect()

    def _candidate_dirs(self) -> list[Path]:
        deriv = self.app.state.defaults.get("derivatives_root", "")
        candidates = []
        if deriv:
            candidates.append(Path(deriv).expanduser() / "slurm")
        candidates += [
            Path("/scratch/jonathanwade/mous_derivatives/slurm"),
            Path.home() / "mous_derivatives" / "slurm",
        ]
        return candidates

    def _autodetect(self) -> None:
        if self._recent_log_paths:
            newest = self._recent_log_paths[0]
            self.query_one("#log-path-input", Input).value = str(newest)
            self._load_log(newest)
            return
        for slurm_dir in self._candidate_dirs():
            if not slurm_dir.exists():
                continue
            for pattern in ("mous_driver_*.err", "mous_fmriprep_*.err", "*.err"):
                log = latest_log(slurm_dir, pattern)
                if log:
                    self.query_one("#log-path-input", Input).value = str(log)
                    self._load_log(log)
                    return
        self.notify("No logs auto-detected — paste a path and click Load.", severity="warning")

    def _refresh_recent_logs(self) -> None:
        rows: list[tuple[str, Path, float]] = []
        for slurm_dir in self._candidate_dirs():
            if not slurm_dir.exists():
                continue
            for pattern in ("mous_driver_*.out", "mous_driver_*.err", "fmriprep_*.out", "fmriprep_*.err", "*.out", "*.err"):
                for p in slurm_dir.glob(pattern):
                    if p.is_file():
                        rows.append((self._log_kind(p.name), p, p.stat().st_mtime))
        # De-duplicate across patterns/dirs by absolute path
        dedup: dict[str, tuple[str, Path, float]] = {}
        for kind, path, mtime in rows:
            dedup[str(path.resolve())] = (kind, path, mtime)
        ordered = sorted(dedup.values(), key=lambda x: x[2], reverse=True)[:25]
        self._recent_log_paths = [path for _, path, _ in ordered]

        table = self.query_one("#recent-logs-table", DataTable)
        table.clear()
        for kind, path, mtime in ordered:
            ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            table.add_row(kind, ts, path.name)

    def _log_kind(self, filename: str) -> str:
        lower = filename.lower()
        if "fmriprep" in lower:
            return "fMRI Preprocessing"
        if "driver" in lower:
            return "Driver"
        if "fetch" in lower or "mous_fetch_rdr" in lower:
            return "Download"
        if "bids" in lower:
            return "BIDS"
        return "other"

    def _load_log(self, path: Path) -> None:
        text = tail_text(path, lines=200)
        if not text:
            self.query_one("#failure-banner", Static).update(
                f"[dim]  Log file empty or not found: {path}[/dim]"
            )
            return

        kind   = classify_failure(text)
        banner = FAILURE_HINTS.get(kind, FAILURE_HINTS["unknown"])
        self.query_one("#failure-banner", Static).update(f"  {banner}")

        rl = self.query_one("#log-output", RichLog)
        rl.clear()
        rl.write(text)

    @on(Button.Pressed, "#btn-back")
    def action_back(self) -> None: self.app.pop_screen()

    @on(Button.Pressed, "#btn-load-log")
    def _on_load(self, _) -> None:
        p = self.query_one("#log-path-input", Input).value.strip()
        if p:
            self._load_log(Path(p))

    @on(Button.Pressed, "#btn-autodetect")
    def _on_autodetect(self, _) -> None:
        self._autodetect()

    @on(Button.Pressed, "#btn-refresh-recent")
    def _on_refresh_recent(self, _) -> None:
        self._refresh_recent_logs()
        self.notify("Recent logs refreshed")

    @on(Button.Pressed, "#btn-load-selected")
    def _on_load_selected(self, _) -> None:
        table = self.query_one("#recent-logs-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None or row_idx < 0 or row_idx >= len(self._recent_log_paths):
            self.notify("Select a recent log row first", severity="warning")
            return
        path = self._recent_log_paths[row_idx]
        self.query_one("#log-path-input", Input).value = str(path)
        self._load_log(path)

    def action_refresh_log(self) -> None:
        self._refresh_recent_logs()
        p = self.query_one("#log-path-input", Input).value.strip()
        if p:
            self._load_log(Path(p))


# ── App shell ─────────────────────────────────────────────────────────────────

class OpsApp(App[None]):
    TITLE = "MOUS Ops"
    CSS   = APP_CSS

    def __init__(self) -> None:
        super().__init__()
        self.state = load_state()
        # Wizard state shared across wizard screens
        self.wizard_config:      str       = self.state.last_config
        self.wizard_subjects:    list[str] = []
        self.wizard_preset_name: str       = "full_submit"

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen())


def run_ops_app() -> None:
    OpsApp().run()
