from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mous_pipeline.m8_reports.quarto_report import render_quarto, render_quarto_suite


def _cfg(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(derivatives_root=tmp_path / "derivatives")


def test_render_quarto_uses_cumulative_template_once(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    qmd = tmp_path / "reports" / "subject_full_report.qmd"
    qmd.parent.mkdir(parents=True, exist_ok=True)
    qmd.write_text("---\ntitle: test\n---\n")

    cfg = _cfg(tmp_path)
    subject = "A2002"
    calls: list[list[str]] = []

    monkeypatch.setattr("mous_pipeline.m8_reports.quarto_report.shutil.which", lambda exe: "/usr/bin/quarto")

    def _fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        calls.append(cmd)
        out_idx = cmd.index("--output") + 1
        Path(cmd[out_idx]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[out_idx]).write_text("<html>ok</html>")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("mous_pipeline.m8_reports.quarto_report.subprocess.run", _fake_run)

    out = render_quarto(subject, cfg)
    assert out is not None
    assert out.exists()
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0:3] == ["quarto", "render", str(qmd)]
    assert cmd.count("-P") == 2
    assert f"subject:{subject}" in cmd
    assert f"export_dir:{cfg.derivatives_root / subject / 'm8_reports' / 'exports'}" in cmd


def test_render_quarto_suite_returns_single_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    qmd = tmp_path / "reports" / "subject_full_report.qmd"
    qmd.parent.mkdir(parents=True, exist_ok=True)
    qmd.write_text("---\ntitle: test\n---\n")

    cfg = _cfg(tmp_path)
    subject = "A2010"
    monkeypatch.setattr("mous_pipeline.m8_reports.quarto_report.shutil.which", lambda exe: "/usr/bin/quarto")

    def _fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        out_idx = cmd.index("--output") + 1
        Path(cmd[out_idx]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[out_idx]).write_text("<html>ok</html>")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("mous_pipeline.m8_reports.quarto_report.subprocess.run", _fake_run)

    outputs = render_quarto_suite(subject, cfg)
    assert len(outputs) == 1
    assert outputs[0].name == f"{subject}_quarto_report.html"


def test_subject_full_report_template_has_backcompat_guards() -> None:
    template = Path("reports/subject_full_report.qmd").read_text()

    # Aim 1/2 R chunks should skip gracefully when mixed old/new CSV schemas are present.
    assert "Aim 1 model skipped (missing trial columns)" in template
    assert "Aim 2 model skipped (missing joined columns)" in template
    assert "No prestim_beta/condition columns found; Aim 1 figure skipped." in template
    assert "No prestim_beta/mtg_beta/condition columns found; Aim 2 figure skipped." in template


def test_subject_full_report_template_mentions_new_optional_metrics() -> None:
    template = Path("reports/subject_full_report.qmd").read_text()
    for key in [
        "aim1_prestim_auc_guard_reason",
        "alpha_dci_zinnen",
        "m10_hrf_lag_sweep_tables",
        "m11_coupling_hrf_lag_sweep",
        "aim3_two_dipole_z_threshold",
        "aim3_two_dipole_passes_threshold",
        "m12_decision",
        "aim1_prestim_topography_artifact",
    ]:
        assert key in template
