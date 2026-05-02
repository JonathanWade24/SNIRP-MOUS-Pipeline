from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest

from mous_pipeline import cli


def test_gui_command_prints_deprecation_and_launches_streamlit(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["mous-pipeline", "gui", "--port", "8765", "--config", "configs/pilot_A2002.yaml"])
    monkeypatch.setattr("mous_pipeline.cli.shutil.which", lambda exe: "/usr/bin/streamlit" if exe == "streamlit" else None)

    launched: dict[str, object] = {}

    def _fake_run(cmd: list[str], check: bool):
        launched["cmd"] = cmd
        launched["check"] = check
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("mous_pipeline.cli.subprocess.run", _fake_run)
    cli.main()

    out = capsys.readouterr()
    assert "DEPRECATION:" in out.err
    assert "scheduled for removal in v0.3.0" in out.err
    assert launched["check"] is False
    assert launched["cmd"][0] == "/usr/bin/streamlit"
    assert launched["cmd"][1] == "run"
    assert launched["cmd"][2] == "src/mous_pipeline/gui_streamlit.py"


def test_gui_command_missing_streamlit_exits_with_install_hint(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["mous-pipeline", "gui"])
    monkeypatch.setattr("mous_pipeline.cli.shutil.which", lambda _exe: None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    out = capsys.readouterr()
    assert exc.value.code == 1
    assert "DEPRECATION:" in out.err
    assert "Streamlit is not installed in this environment." in out.err
