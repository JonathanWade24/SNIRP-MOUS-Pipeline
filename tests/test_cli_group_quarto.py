from __future__ import annotations

import json
from pathlib import Path

from mous_pipeline import cli


def test_group_command_writes_summary_and_calls_group_quarto(tmp_path, monkeypatch) -> None:
    derivatives = tmp_path / "derivatives"
    mf = derivatives / "A2002" / "m9_orchestration" / "sub-A2002_run_manifest.json"
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(json.dumps({"metrics": {"dci_zinnen": 0.2}}))

    called: dict[str, object] = {}

    monkeypatch.setattr("sys.argv", ["mous-pipeline", "group", "--derivatives-root", str(derivatives)])
    monkeypatch.setattr("mous_pipeline.cli.run_group_model", lambda metrics, test: {"metrics": {}, "test": test})

    def _fake_render_group_quarto(*, derivatives_root: Path, summary_json: Path):
        called["derivatives_root"] = derivatives_root
        called["summary_json"] = summary_json
        return derivatives_root / "group_reports" / "group_quarto_report.html"

    monkeypatch.setattr("mous_pipeline.cli.render_group_quarto", _fake_render_group_quarto)
    cli.main()
    assert (derivatives / "group_summary.json").exists()
    assert called["derivatives_root"] == derivatives
    assert called["summary_json"] == derivatives / "group_summary.json"
