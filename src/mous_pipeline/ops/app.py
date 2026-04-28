from __future__ import annotations

from copy import deepcopy
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
    build_bids_convert_cmd,
    build_bids_validate_cmd,
    build_download_cmd,
    build_submit_cmd,
    discover_subjects,
    execute_submit_cmd,
    run_cmd,
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


PRESET_DESCRIPTIONS: dict[str, str] = {
    "download_only":          "Download subject data from RDR only. No processing.",
    "bids_convert_validate":  "Run BIDS conversion + mne_bids validation. Good first step before submit.",
    "dry_run_submit":         "Preview palmetto_submit.sh commands without running anything. Safe to use anytime.",
    "full_submit":            "Submit the full pipeline via palmetto_submit.sh. Skips m5 (recon-all).",
    "m5_enabled_submit":      "Full pipeline including m5 (recon-all). Requires FreeSurfer outputs in subjects_dir.",
    "fmriprep_only_submit":   "Submit fMRIPrep-focused run for selected subjects.",
}

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
            yield Button("✓ All",          id="btn-all",  variant="default")
            yield Button("✗ None",         id="btn-none", variant="default")

        yield SelectionList[str](id="subject-list")

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
        if not subjects:
            self.notify("No subjects found — check config/data-root paths.", severity="warning")

    @on(Button.Pressed, "#btn-load")
    def _on_load(self, _) -> None:
        self._load_subjects()

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
            yield Select([(n, n) for n in names], value=cur, id="preset-select")

        yield Static(
            PRESET_DESCRIPTIONS.get(self.app.wizard_preset_name, ""),
            id="preset-desc",
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
            f"[dim]Preset:[/dim] [bold]{self.app.wizard_preset_name}[/bold]  "
            f"[dim]Subjects:[/dim] [bold]{', '.join('sub-' + s for s in self.app.wizard_subjects)}[/bold]",
            id="run-summary",
        )

        yield Static("[dim]← click Preview or Dry Run to generate command[/dim]", id="cmd-preview")

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
            "[bold]Submitting:[/bold]\n" + " ".join(cmd) + "\n\n[dim]Running…[/dim]"
        )
        job, proc = execute_submit_cmd(
            cmd,
            config_path=self.app.wizard_config,
            subjects=self.app.wizard_subjects,
            kind=f"preset:{self.app.wizard_preset_name}",
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


# ── Log Viewer ────────────────────────────────────────────────────────────────

class LogScreen(Screen):
    BINDINGS = [
        Binding("escape", "action_back", "Back"),
        Binding("r", "refresh_log",      "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("  Log Viewer  ›  Latest SLURM Error Logs", classes="wizard-header")

        with Horizontal(classes="frow"):
            yield Label("Log file:", classes="flabel")
            yield Input(placeholder="paste path or use Auto-detect", id="log-path-input")
            yield Button("↺ Load",       id="btn-load-log",  variant="default")
            yield Button("Auto-detect",  id="btn-autodetect", variant="default")

        yield Static("", id="failure-banner")
        yield RichLog(id="log-output", highlight=True, markup=True, wrap=False)

        with Horizontal(classes="nav-bar"):
            yield Button("← Back", id="btn-back", variant="default")

        yield Footer()

    def on_mount(self) -> None:
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

    def action_refresh_log(self) -> None:
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
