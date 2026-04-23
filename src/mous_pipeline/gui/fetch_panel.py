"""Fetch panel for downloading subject folders via repocli."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import ipywidgets as widgets

from ..config import PipelineConfig
from ..m0_intake.repocli_rdr import build_repocli_get_command, remote_subject_path


def create_fetch_panel(
    get_config: Callable[[], tuple[Path, PipelineConfig] | None],
) -> widgets.Widget:
    subject_input = widgets.Text(value="A2002", description="Subject")
    download_btn = widgets.Button(description="Download subject", button_style="primary")
    status_label = widgets.HTML("<b>Status:</b> idle")
    progress = widgets.IntProgress(value=0, min=0, max=100, description="Fetch")
    output = widgets.Output(layout=widgets.Layout(border="1px solid #ddd", max_height="280px", overflow="auto"))

    def run_download(_: object) -> None:
        cfg_bundle = get_config()
        output.clear_output()
        if not cfg_bundle:
            status_label.value = "<b>Status:</b> failed (load config first)"
            return
        _, cfg = cfg_bundle
        collection = cfg.rdr.collection_path
        if not collection:
            status_label.value = "<b>Status:</b> failed (rdr.collection_path missing)"
            return

        subject = subject_input.value.strip()
        remote = remote_subject_path(collection, subject)
        cmd = build_repocli_get_command(remote_path=remote, local_dir=cfg.data_root.resolve())
        status_label.value = "<b>Status:</b> downloading"
        progress.value = 0
        progress.bar_style = "info"
        download_btn.disabled = True

        def worker() -> None:
            pulse_running = [True]

            def pulse() -> None:
                value = 0
                while pulse_running[0]:
                    value = (value + 10) % 100
                    progress.value = value
                    time.sleep(0.2)

            pulse_thread = threading.Thread(target=pulse, daemon=True)
            pulse_thread.start()
            try:
                with output:
                    print("$ " + " ".join(cmd))
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                assert proc.stdout is not None
                for line in proc.stdout:
                    output.append_stdout(line)
                code = proc.wait()
                if code == 0:
                    progress.value = 100
                    progress.bar_style = "success"
                    status_label.value = "<b>Status:</b> done"
                else:
                    progress.bar_style = "danger"
                    status_label.value = f"<b>Status:</b> failed (exit {code})"
            except Exception as exc:  # pragma: no cover - notebook UX path
                progress.bar_style = "danger"
                status_label.value = f"<b>Status:</b> failed ({exc})"
            finally:
                pulse_running[0] = False
                download_btn.disabled = False

        threading.Thread(target=worker, daemon=True).start()

    download_btn.on_click(run_download)
    return widgets.VBox(
        [
            widgets.HTML("<h3>Fetch from RDR</h3>"),
            subject_input,
            download_btn,
            status_label,
            progress,
            output,
        ]
    )
