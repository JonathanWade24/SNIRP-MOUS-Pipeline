"""Results panel for viewing manifests and reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import ipywidgets as widgets
import matplotlib.pyplot as plt

from ..config import PipelineConfig


def _manifest_path(derivatives_root: Path, subject: str) -> Path:
    return derivatives_root / f"sub-{subject}" / "m9_orchestration" / f"sub-{subject}_run_manifest.json"


def create_results_panel(
    get_config: Callable[[], tuple[Path, PipelineConfig] | None],
) -> widgets.Widget:
    subject_dropdown = widgets.Dropdown(options=[], description="Subject")
    refresh_btn = widgets.Button(description="Refresh subjects")
    load_btn = widgets.Button(description="Load results", button_style="primary")
    verdict_badge = widgets.HTML("<b>Pilot verdict:</b> (none)")
    metrics_html = widgets.HTML()
    report_link = widgets.HTML()
    plot_output = widgets.Output(layout=widgets.Layout(border="1px solid #ddd"))

    def refresh_subjects(_: object | None = None) -> None:
        cfg_bundle = get_config()
        if not cfg_bundle:
            subject_dropdown.options = []
            return
        _, cfg = cfg_bundle
        root = cfg.derivatives_root
        options = []
        if root.exists():
            for path in sorted(root.glob("sub-*")):
                if path.is_dir():
                    options.append(path.name.replace("sub-", "", 1))
        subject_dropdown.options = options
        if options:
            subject_dropdown.value = options[0]

    def load_results(_: object) -> None:
        cfg_bundle = get_config()
        if not cfg_bundle or not subject_dropdown.value:
            return
        _, cfg = cfg_bundle
        subject = str(subject_dropdown.value)
        manifest_path = _manifest_path(cfg.derivatives_root, subject)
        if not manifest_path.exists():
            verdict_badge.value = "<b>Pilot verdict:</b> missing manifest"
            metrics_html.value = ""
            report_link.value = ""
            plot_output.clear_output()
            return

        manifest = json.loads(manifest_path.read_text())
        metrics = manifest.get("metrics", {})
        verdict = metrics.get("pilot_verdict", "unknown")
        verdict_color = {"GO": "#2e7d32", "MARGINAL": "#f9a825", "NO-GO": "#b71c1c"}.get(verdict, "#616161")
        verdict_badge.value = (
            "<b>Pilot verdict:</b> "
            f'<span style="color: white; background: {verdict_color}; padding: 2px 8px; border-radius: 8px;">{verdict}</span>'
        )

        keys = [
            "n_trials",
            "n_zinnen",
            "n_woorden",
            "n_rest",
            "dci_zinnen",
            "dci_woorden",
            "dci_rest",
            "p_task_vs_rest",
            "p_rayleigh_zinnen",
        ]
        rows = "".join(
            f"<tr><td><code>{key}</code></td><td>{metrics.get(key, '')}</td></tr>"
            for key in keys
        )
        metrics_html.value = (
            "<table>"
            "<thead><tr><th>Metric</th><th>Value</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

        report_path = cfg.derivatives_root / f"sub-{subject}" / "m8_reports" / f"sub-{subject}_report.html"
        if report_path.exists():
            report_link.value = f'<a href="file://{report_path.resolve()}" target="_blank">Open HTML report</a>'
        else:
            report_link.value = "<em>HTML report not found</em>"

        stage_timings = manifest.get("params", {}).get("stage_timings_s", {})
        plot_output.clear_output()
        with plot_output:
            if stage_timings:
                names = list(stage_timings.keys())
                vals = [float(stage_timings[n]) for n in names]
                fig, ax = plt.subplots(figsize=(8, 3))
                ax.bar(names, vals)
                ax.set_ylabel("seconds")
                ax.set_title(f"sub-{subject} stage timings")
                plt.tight_layout()
                plt.show()
            else:
                print("No stage timings available in manifest.")

    refresh_btn.on_click(refresh_subjects)
    load_btn.on_click(load_results)
    refresh_subjects(None)

    return widgets.VBox(
        [
            widgets.HTML("<h3>Results</h3>"),
            widgets.HBox([subject_dropdown, refresh_btn, load_btn]),
            verdict_badge,
            metrics_html,
            report_link,
            plot_output,
        ]
    )
