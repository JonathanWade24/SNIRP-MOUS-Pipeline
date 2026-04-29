from __future__ import annotations

from pathlib import Path

from mous_pipeline.config import PipelineConfig
from mous_pipeline.m5_source.forward import build_forward_model


class _DummyRaw:
    info = {}


def test_build_forward_model_reports_missing_bem_surfaces(tmp_path: Path) -> None:
    cfg = PipelineConfig()
    cfg.source.subjects_dir = str(tmp_path / "freesurfer")
    cfg.source.use_fsaverage = False
    cfg.source.trans = "fsaverage"
    subject_root = Path(cfg.source.subjects_dir) / "sub-A2002"
    (subject_root / "bem").mkdir(parents=True, exist_ok=True)

    try:
        build_forward_model("A2002", _DummyRaw(), cfg)
    except FileNotFoundError as exc:
        msg = str(exc)
        assert "Missing BEM surfaces for m5 subject sub-A2002" in msg
        assert "inner_skull.surf" in msg
        assert "ops prep-bem" in msg
    else:
        raise AssertionError("Expected FileNotFoundError for missing BEM surfaces")
