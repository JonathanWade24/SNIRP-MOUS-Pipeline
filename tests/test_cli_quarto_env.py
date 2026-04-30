from __future__ import annotations

from types import SimpleNamespace

from mous_pipeline.cli import _check_quarto_env


def test_check_quarto_env_missing_rscript(monkeypatch) -> None:
    monkeypatch.setattr(
        "mous_pipeline.cli.shutil.which",
        lambda exe: "/usr/bin/quarto" if exe == "quarto" else None,
    )

    ok, messages = _check_quarto_env()
    assert ok is False
    assert any("missing binary: Rscript" in msg for msg in messages)


def test_check_quarto_env_reports_missing_r_packages(monkeypatch) -> None:
    monkeypatch.setattr(
        "mous_pipeline.cli.shutil.which",
        lambda exe: "/usr/bin/tool" if exe in {"quarto", "Rscript"} else None,
    )

    def _fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        assert cmd[0] == "Rscript"
        return SimpleNamespace(returncode=2, stdout="lmerTest,readr", stderr="")

    monkeypatch.setattr("mous_pipeline.cli.subprocess.run", _fake_run)
    ok, messages = _check_quarto_env()
    assert ok is False
    assert any("missing R packages: lmerTest,readr" in msg for msg in messages)


def test_check_quarto_env_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        "mous_pipeline.cli.shutil.which",
        lambda exe: f"/usr/bin/{exe}" if exe in {"quarto", "Rscript"} else None,
    )

    def _fake_run(cmd: list[str], check: bool, capture_output: bool, text: bool):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("mous_pipeline.cli.subprocess.run", _fake_run)
    ok, messages = _check_quarto_env()
    assert ok is True
    assert any("R packages: OK" in msg for msg in messages)
