"""Module 8 lightweight HTML reporting."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from ..io import stage_output_dir
from .figures import dci_timecourse, prestim_topography, rose_plot


def _fig_to_base64(fig) -> str:
    buff = io.BytesIO()
    fig.savefig(buff, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buff.getvalue()).decode("utf-8")


def _fmt_metric(value) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


_METRIC_LABELS: dict[str, str] = {
    "run_status":               "Run status",
    "n_trials":                 "Total trials",
    "n_zinnen":                 "ZINNEN trials",
    "n_woorden":                "WOORDEN trials",
    "n_rest":                   "REST pseudo-epochs",
    "dci_zinnen":               "Mean DCI – ZINNEN",
    "dci_woorden":              "Mean DCI – WOORDEN",
    "dci_rest":                 "Mean DCI – REST",
    "p_task_vs_rest":           "p (task vs REST, permutation)",
    "p_woorden_vs_rest":        "p (WOORDEN vs REST)",
    "p_zinnen_vs_woorden":      "p (ZINNEN vs WOORDEN)",
    "p_rayleigh_zinnen":        "Rayleigh p – ZINNEN",
    "p_rayleigh_woorden":       "Rayleigh p – WOORDEN",
    "source_dci_zinnen":        "Source DCI – ZINNEN (m5)",
    "m5_n_labels":              "m5 ROI labels computed",
    "m5_n_stcs":                "m5 source estimates",
    "m5_error":                 "m5 error",
    "m5_skipped_reason":        "m5 skipped reason",
}


def _timing_bars_html(timings: dict[str, float]) -> str:
    """Stage timing table with inline bar chart column."""
    if not timings:
        return "<p><em>No timing data.</em></p>"
    max_s = max(timings.values()) or 1.0
    rows = []
    for stage, seconds in sorted(timings.items(), key=lambda x: -x[1]):
        pct = int(seconds / max_s * 100)
        bar = (
            f'<div style="width:{pct}%;min-width:2px;height:12px;'
            f'background:#1976d2;border-radius:2px;display:inline-block;"></div>'
        )
        rows.append(
            f"<tr>"
            f"<td style='width:110px;font-weight:500;'>{stage}</td>"
            f"<td style='width:70px;text-align:right;padding-right:10px;'>{seconds:.1f} s</td>"
            f"<td style='width:220px;vertical-align:middle;'>{bar}</td>"
            f"</tr>"
        )
    return (
        "<table style='border:none;'>"
        "<tr>"
        "<th style='text-align:left;background:#f7f7f7;'>Stage</th>"
        "<th style='text-align:right;background:#f7f7f7;padding-right:10px;'>Duration</th>"
        "<th style='background:#f7f7f7;'></th>"
        "</tr>"
        + "".join(rows)
        + "</table>"
    )


def render_subject(
    subject: str,
    cfg,
    payload: dict,
    *,
    dirs_z: np.ndarray | None = None,
    dirs_w: np.ndarray | None = None,
    dirs_r: np.ndarray | None = None,
    sliding_t: np.ndarray | None = None,
    sliding_dci_z: np.ndarray | None = None,
) -> Path:
    out_dir = stage_output_dir(cfg, subject, "m8_reports")
    out_path = out_dir / f"{subject}_report.html"
    payload_for_display = dict(payload)
    payload_metrics = dict(payload_for_display.get("metrics", {}) or {})
    payload_metrics.pop("pilot_verdict", None)
    payload_for_display["metrics"] = payload_metrics
    pretty = json.dumps(payload_for_display, indent=2)
    metrics = payload.get("metrics", {})
    timings = payload.get("stage_timings_s", {})
    outputs = payload.get("outputs", [])

    # Load m5 source directions if written to disk (avoids threading caller with extra arg).
    # Construct path without mkdir so no empty dir is created when m5 never ran.
    m5_out_dir = cfg.derivatives_root / subject / "m5_source"
    source_dirs_npy = m5_out_dir / f"sub-{subject}_source_dirs.npy"
    source_dirs: np.ndarray | None = None
    if source_dirs_npy.exists():
        try:
            source_dirs = np.load(source_dirs_npy)
        except Exception:
            pass

    # ── Rose plots ────────────────────────────────────────────────────────────
    rose_sections: list[str] = []

    if dirs_z is not None and dirs_w is not None and dirs_r is not None:
        fig, axes = plt.subplots(1, 3, figsize=(12, 4), subplot_kw={"projection": "polar"})
        rose_plot(axes[0], dirs_z, "ZINNEN", "#1f77b4")
        rose_plot(axes[1], dirs_w, "WOORDEN", "#2ca02c")
        rose_plot(axes[2], dirs_r, "REST", "#ff7f0e")
        fig.suptitle("Sensor-space wave directions", fontsize=11, y=1.02)
        rose_sections.append(
            f'<h3>Sensor-space</h3>'
            f'<img alt="sensor rose" src="data:image/png;base64,{_fig_to_base64(fig)}" '
            f'style="max-width:100%;">'
        )

    if source_dirs is not None and len(source_dirs) > 0:
        fig, ax = plt.subplots(1, 1, figsize=(5, 5), subplot_kw={"projection": "polar"})
        rose_plot(ax, source_dirs, "Source ZINNEN", "#9467bd")
        fig.suptitle("Source-space wave directions (ZINNEN)", fontsize=11, y=1.02)
        rose_sections.append(
            f'<h3>Source-space (m5 – ZINNEN)</h3>'
            f'<img alt="source rose" src="data:image/png;base64,{_fig_to_base64(fig)}" '
            f'style="max-width:100%;">'
        )

    rose_html = "".join(rose_sections)

    # ── Sliding DCI ───────────────────────────────────────────────────────────
    dci_html = ""
    if sliding_t is not None and sliding_dci_z is not None and len(sliding_t) and len(sliding_dci_z):
        fig, _ = dci_timecourse(sliding_t, sliding_dci_z, None, "ZINNEN")
        dci_html = (
            f'<img alt="sliding dci" src="data:image/png;base64,{_fig_to_base64(fig)}" '
            f'style="max-width:100%;">'
        )

    prestim_topo_html = ""
    prestim_topo_path = metrics.get("aim1_prestim_topography_artifact")
    if prestim_topo_path:
        topo_path = Path(str(prestim_topo_path))
        if topo_path.exists():
            try:
                topo_npz = np.load(topo_path)
                sensor_xy = np.asarray(topo_npz["sensor_xy"])
                channel_power = np.asarray(topo_npz["channel_power"])
                fig, ax = plt.subplots(figsize=(5, 4))
                sc = prestim_topography(ax, sensor_xy, channel_power, title="Pre-stim beta sensor power")
                fig.colorbar(sc, ax=ax, shrink=0.8)
                prestim_topo_html = (
                    f'<img alt="prestim topography" src="data:image/png;base64,{_fig_to_base64(fig)}" '
                    f'style="max-width:100%;">'
                )
            except Exception:
                prestim_topo_html = ""

    # ── Key metrics table ─────────────────────────────────────────────────────
    key_metric_order = list(_METRIC_LABELS.keys())
    rows_html = "".join(
        f"<tr><td style='color:#555;font-size:0.88em;'>{_METRIC_LABELS.get(k, k)}</td>"
        f"<td><strong>{_fmt_metric(metrics.get(k, ''))}</strong></td></tr>"
        for k in key_metric_order
        if k in metrics
    )
    # Include any extra keys not in the ordered list
    shown = set(key_metric_order)
    extra_rows = "".join(
        f"<tr><td style='color:#555;font-size:0.88em;'>{k}</td>"
        f"<td>{_fmt_metric(v)}</td></tr>"
        for k, v in metrics.items()
        if k not in shown
        and not isinstance(v, (dict, list))
        and k not in {"selected_stages", "strict_stage_failures", "skipped_stages"}
    )

    output_rows = "".join(f"<li><code>{o}</code></li>" for o in outputs)
    timing_html = _timing_bars_html(timings)

    # ── CSS ───────────────────────────────────────────────────────────────────
    css = (
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "padding:28px 36px;line-height:1.45;max-width:960px;margin:0 auto;color:#212121;}"
        "h1{margin-top:0;}"
        "h2{border-bottom:2px solid #e0e0e0;padding-bottom:6px;margin-top:32px;}"
        "h3{color:#444;margin:12px 0 6px;}"
        "table{border-collapse:collapse;min-width:480px;}"
        "th,td{border:1px solid #e0e0e0;padding:7px 12px;vertical-align:top;}"
        "th{background:#f5f5f5;text-align:left;font-weight:600;}"
        "code{background:#f5f5f5;padding:2px 5px;border-radius:3px;font-size:0.88em;}"
        "pre{background:#f9f9f9;padding:14px;overflow:auto;border:1px solid #e8e8e8;"
        "border-radius:4px;font-size:0.83em;}"
        ".badge{display:inline-block;border-radius:4px;padding:3px 8px;"
        "font-size:0.85em;font-weight:600;margin-left:6px;}"
        ".m5-warn{background:#fff3e0;border-left:4px solid #e65100;padding:10px 14px;"
        "border-radius:0 4px 4px 0;margin:12px 0;}"
    )

    # ── m5 status banner ──────────────────────────────────────────────────────
    m5_banner = ""
    if metrics.get("m5_error"):
        m5_banner = (
            f'<div class="m5-warn">⚠ <strong>m5 error:</strong> '
            f'{metrics["m5_error"]}</div>'
        )
    elif metrics.get("m5_skipped_reason"):
        m5_banner = (
            f'<div class="m5-warn">ℹ <strong>m5 skipped:</strong> '
            f'{metrics["m5_skipped_reason"]}</div>'
        )

    out_path.write_text(
        f"<html><head><meta charset='utf-8'>"
        f"<title>Subject {subject} – MOUS Report</title>"
        f"<style>{css}</style></head><body>"
        f"<h1>Subject {subject}</h1>"
        f"{m5_banner}"
        f"<h2>Key metrics</h2>"
        f"<table><tr><th>Metric</th><th>Value</th></tr>{rows_html}{extra_rows}</table>"
        f"<h2>Stage timings</h2>{timing_html}"
        f"<h2>Direction rose plots</h2>{rose_html if rose_html else '<p><em>No direction data.</em></p>'}"
        f"<h2>Sliding DCI (ZINNEN)</h2>{dci_html if dci_html else '<p><em>No DCI timecourse data.</em></p>'}"
        f"<h2>Pre-stim topography</h2>{prestim_topo_html if prestim_topo_html else '<p><em>No topography artifact available.</em></p>'}"
        f"<h2>Generated outputs</h2><ul>{output_rows}</ul>"
        f"<h2>Raw payload</h2><details><summary>Expand JSON</summary><pre>{pretty}</pre></details>"
        f"</body></html>"
    )
    return out_path
