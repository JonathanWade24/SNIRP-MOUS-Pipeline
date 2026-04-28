"""Dedicated Aim2 HTML reporting (subject + group)."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from ..m7_stats.group import run_group_model


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (dict, list)):
        return html.escape(json.dumps(value))
    return html.escape(str(value))


def _stage_status(metrics: dict, stage: str) -> tuple[str, str]:
    err = metrics.get(f"{stage}_error")
    skip = metrics.get(f"{stage}_skipped_reason")
    if err:
        return ("ERROR", str(err))
    if skip:
        return ("SKIPPED", str(skip))
    return ("OK", "")


def render_aim2_subject(subject: str, cfg, *, metrics: dict, joined_csv: Path | None = None) -> Path:
    out_dir = cfg.derivatives_root / subject / "m8_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{subject}_aim2_summary.html"

    joined_rows = ""
    joined_present = False
    if joined_csv and joined_csv.exists():
        joined_present = True
        try:
            df = pd.read_csv(joined_csv)
            joined_rows = f"<li>Joined table rows: <strong>{len(df)}</strong></li>"
        except Exception as exc:
            joined_rows = f"<li>Joined table read error: <code>{html.escape(str(exc))}</code></li>"

    m10_status, m10_note = _stage_status(metrics, "m10")
    m11_status, m11_note = _stage_status(metrics, "m11")
    m12_status, m12_note = _stage_status(metrics, "m12")

    m11 = metrics.get("m11_coupling") or {}
    m12 = metrics.get("m12_null_summary") or {}

    page = f"""<html><head><meta charset="utf-8">
<title>{html.escape(subject)} Aim2 summary</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 980px; margin: 0 auto; padding: 28px; }}
h1,h2 {{ margin-bottom: 8px; }}
table {{ border-collapse: collapse; width: 100%; }}
th,td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; text-align: left; }}
th {{ background: #f5f5f5; }}
code {{ background: #f7f7f7; padding: 1px 4px; border-radius: 3px; }}
</style></head><body>
<h1>Aim2 Summary: {html.escape(subject)}</h1>
<h2>Status</h2>
<table>
  <tr><th>Stage</th><th>Status</th><th>Note</th></tr>
  <tr><td>m10 fMRI prep + GLM</td><td>{_fmt(m10_status)}</td><td>{_fmt(m10_note)}</td></tr>
  <tr><td>m11 MEG-fMRI coupling</td><td>{_fmt(m11_status)}</td><td>{_fmt(m11_note)}</td></tr>
  <tr><td>m12 null model</td><td>{_fmt(m12_status)}</td><td>{_fmt(m12_note)}</td></tr>
</table>

<h2>m10 Join Diagnostics</h2>
<ul>
  <li>m10_n_trials_joined: <strong>{_fmt(metrics.get("m10_n_trials_joined"))}</strong></li>
  <li>Joined CSV exists: <strong>{'yes' if joined_present else 'no'}</strong></li>
  {joined_rows}
</ul>

<h2>m11 Coupling</h2>
<pre>{_fmt(m11)}</pre>

<h2>m12 Null Summary</h2>
<pre>{_fmt(m12)}</pre>

<h2>Key Metrics</h2>
<ul>
  <li>run_status: <strong>{_fmt(metrics.get("run_status"))}</strong></li>
  <li>pilot_verdict: <strong>{_fmt(metrics.get("pilot_verdict"))}</strong></li>
  <li>aim3_two_dipole_z: <strong>{_fmt(metrics.get("aim3_two_dipole_z"))}</strong></li>
</ul>
</body></html>"""
    out_path.write_text(page)
    return out_path


def render_aim2_group(derivatives_root: Path, *, test: str = "wilcoxon") -> Path | None:
    manifests = sorted(derivatives_root.glob("*/m9_orchestration/*_run_manifest.json"))
    subject_metrics: list[dict] = []
    status_rows: list[tuple[str, str, str, str]] = []
    for mf in manifests:
        try:
            payload = json.loads(mf.read_text())
            metrics = payload.get("metrics", {}) or {}
        except Exception:
            continue
        subject_id = mf.parent.parent.name
        m = dict(metrics)
        m["subject_id"] = subject_id
        subject_metrics.append(m)
        status_rows.append(
            (
                subject_id,
                _stage_status(metrics, "m10")[0],
                _stage_status(metrics, "m11")[0],
                _stage_status(metrics, "m12")[0],
            )
        )
    if not subject_metrics:
        return None
    group_stats = run_group_model(subject_metrics, test=test)
    rows_html = "".join(
        f"<tr><td>{html.escape(s)}</td><td>{m10}</td><td>{m11}</td><td>{m12}</td></tr>"
        for s, m10, m11, m12 in status_rows
    )
    out_path = derivatives_root / "group_aim2_summary.html"
    page = f"""<html><head><meta charset="utf-8">
<title>Aim2 Group Summary</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 980px; margin: 0 auto; padding: 28px; }}
table {{ border-collapse: collapse; width: 100%; }}
th,td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f5f5f5; }}
</style></head><body>
<h1>Aim2 Group Summary</h1>
<p>Subjects with manifests: <strong>{len(subject_metrics)}</strong></p>
<h2>Per-subject stage status</h2>
<table>
  <tr><th>Subject</th><th>m10</th><th>m11</th><th>m12</th></tr>
  {rows_html}
</table>
<h2>Group stats</h2>
<pre>{html.escape(json.dumps(group_stats, indent=2))}</pre>
</body></html>"""
    out_path.write_text(page)
    return out_path
