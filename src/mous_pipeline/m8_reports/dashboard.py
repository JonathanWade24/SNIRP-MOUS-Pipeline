"""Module 8 lightweight HTML reporting."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from ..io import stage_output_dir
from .figures import dci_timecourse, rose_plot


def _fig_to_base64(fig) -> str:
    buff = io.BytesIO()
    fig.savefig(buff, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buff.getvalue()).decode("utf-8")


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
    pretty = json.dumps(payload, indent=2)
    metrics = payload.get("metrics", {})

    rose_imgs: list[str] = []
    if dirs_z is not None and dirs_w is not None and dirs_r is not None:
        fig, axes = plt.subplots(1, 3, figsize=(12, 4), subplot_kw={"projection": "polar"})
        rose_plot(axes[0], dirs_z, "ZINNEN", "#1f77b4")
        rose_plot(axes[1], dirs_w, "WOORDEN", "#2ca02c")
        rose_plot(axes[2], dirs_r, "REST", "#ff7f0e")
        rose_imgs.append(_fig_to_base64(fig))

    dci_img = ""
    if sliding_t is not None and sliding_dci_z is not None and len(sliding_t) and len(sliding_dci_z):
        fig, _ = dci_timecourse(sliding_t, sliding_dci_z, None, "ZINNEN")
        dci_img = _fig_to_base64(fig)

    rows = "".join(
        f"<tr><td>{k}</td><td>{metrics.get(k, '')}</td></tr>"
        for k in [
            "n_trials",
            "n_zinnen",
            "n_woorden",
            "n_rest",
            "dci_zinnen",
            "dci_woorden",
            "dci_rest",
            "p_task_vs_rest",
            "p_woorden_vs_rest",
            "p_zinnen_vs_woorden",
            "p_rayleigh_zinnen",
            "p_rayleigh_woorden",
            "pilot_verdict",
        ]
    )
    rose_html = "".join(f'<img alt="rose" src="data:image/png;base64,{img}" style="max-width:100%;">' for img in rose_imgs)
    dci_html = f'<img alt="dci" src="data:image/png;base64,{dci_img}" style="max-width:100%;">' if dci_img else ""
    out_path.write_text(
        f"<html><body>"
        f"<h1>Subject {subject} report</h1>"
        f"<p>Pipeline stage summary, QA metrics, and gating verdict.</p>"
        f"<h2>Key metrics</h2><table border='1' cellpadding='6' cellspacing='0'>{rows}</table>"
        f"<h2>Direction rose plots</h2>{rose_html}"
        f"<h2>Sliding DCI</h2>{dci_html}"
        f"<h2>Raw payload</h2>"
        f"<pre>{pretty}</pre>"
        f"</body></html>"
    )
    return out_path
