"""Run panel to execute the pipeline with progress."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import ipywidgets as widgets

from ..config import PipelineConfig
from ..m9_orchestration.runner import run_subject

STAGES = ["m1", "m2", "m3", "m6a", "m7", "m8", "m9"]


def create_run_panel(
    get_config: Callable[[], tuple[Path, PipelineConfig] | None],
) -> widgets.Widget:
    subject_input = widgets.Text(value="A2002", description="Subject")
    force_checkbox = widgets.Checkbox(value=False, description="Force recompute")
    stage_checks = [widgets.Checkbox(value=True, description=s) for s in STAGES]
    run_btn = widgets.Button(description="Run pipeline", button_style="primary")
    progress = widgets.IntProgress(value=0, min=0, max=len(STAGES), description="Stages")
    status_label = widgets.HTML("<b>Status:</b> idle")
    output = widgets.Output(layout=widgets.Layout(border="1px solid #ddd", max_height="300px", overflow="auto"))

    def selected_stages() -> list[str]:
        return [c.description for c in stage_checks if c.value]

    def on_run(_: object) -> None:
        cfg_bundle = get_config()
        output.clear_output()
        if not cfg_bundle:
            status_label.value = "<b>Status:</b> failed (load config first)"
            return
        cfg_path, cfg = cfg_bundle
        subject = subject_input.value.strip()
        selected = selected_stages()
        if not selected:
            status_label.value = "<b>Status:</b> failed (select at least one stage)"
            return

        skip = set(STAGES) - set(selected)
        progress.max = len(selected)
        progress.value = 0
        progress.bar_style = "info"
        run_btn.disabled = True
        status_label.value = "<b>Status:</b> running"

        done: set[str] = set()

        def callback(stage_name: str) -> None:
            if stage_name in selected and stage_name not in done:
                done.add(stage_name)
                progress.value = len(done)
                output.append_stdout(f"[stage complete] {stage_name}\n")

        def worker() -> None:
            try:
                with output:
                    print(f"Running sub-{subject} with stages: {', '.join(selected)}")
                result = run_subject(
                    subject,
                    cfg,
                    skip=skip if skip else None,
                    force=force_checkbox.value,
                    config_path=cfg_path,
                    progress_callback=callback,
                )
                with output:
                    print(result.summary())
                progress.value = progress.max
                progress.bar_style = "success"
                status_label.value = "<b>Status:</b> done"
            except Exception as exc:  # pragma: no cover - notebook UX path
                progress.bar_style = "danger"
                status_label.value = f"<b>Status:</b> failed ({exc})"
                output.append_stdout(f"{exc}\n")
            finally:
                run_btn.disabled = False

        threading.Thread(target=worker, daemon=True).start()

    run_btn.on_click(on_run)
    return widgets.VBox(
        [
            widgets.HTML("<h3>Run pipeline</h3>"),
            subject_input,
            force_checkbox,
            widgets.HBox(stage_checks),
            run_btn,
            status_label,
            progress,
            output,
        ]
    )
