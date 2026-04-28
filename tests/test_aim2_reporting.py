from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from mous_pipeline.m8_reports.aim2_report import render_aim2_group, render_aim2_subject


def _cfg(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(derivatives_root=tmp_path / "derivatives")


def test_render_aim2_subject_writes_html(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    subject = "A2002"
    joined = cfg.derivatives_root / subject / "m10_fmri" / f"{subject}_trials_joined.csv"
    joined.parent.mkdir(parents=True, exist_ok=True)
    joined.write_text("trial_id,mtg_beta\n1,0.1\n2,0.2\n")

    metrics = {
        "run_status": "done",
        "pilot_verdict": "MARGINAL",
        "m10_n_trials_joined": 2,
        "m11_coupling": {"zinnen_prestim_beta_vs_mtg": {"r": 0.33, "p": 0.04}},
        "m12_null_summary": {"z": 1.9, "p": 0.06},
    }
    out = render_aim2_subject(subject, cfg, metrics=metrics, joined_csv=joined)
    text = out.read_text()
    assert out.exists()
    assert "Aim2 Summary" in text
    assert "m10_n_trials_joined" in text
    assert "m11 Coupling" in text
    assert "m12 Null Summary" in text


def test_render_aim2_group_writes_html(tmp_path: Path) -> None:
    derivatives = tmp_path / "derivatives"
    for sid in ("A2002", "A2003"):
        mf = derivatives / sid / "m9_orchestration" / f"sub-{sid}_run_manifest.json"
        mf.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metrics": {
                "subject_id": sid,
                "run_status": "done",
                "pilot_verdict": "MARGINAL",
                "m11_coupling": {"lme_like": {"r2": 0.2}},
                "m12_null_summary": {"z": 1.5},
            }
        }
        mf.write_text(json.dumps(payload))

    out = render_aim2_group(derivatives)
    assert out is not None
    assert out.exists()
    html = out.read_text()
    assert "Aim2 Group Summary" in html
    assert "A2002" in html
    assert "A2003" in html
