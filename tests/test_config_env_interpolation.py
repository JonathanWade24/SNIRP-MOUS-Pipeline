"""Regression tests for config env-var interpolation and portable paths."""

from __future__ import annotations

from pathlib import Path

from mous_pipeline.config import load_config, resolve_derivatives_root


def test_load_config_expands_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUS_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("MOUS_DERIVATIVES_ROOT", str(tmp_path / "derivatives"))
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "data_root: '${MOUS_DATA_ROOT}'",
                "derivatives_root: '${MOUS_DERIVATIVES_ROOT}'",
                "fmri:",
                "  fs_license_file: '${FS_LICENSE}'",
            ]
        )
    )
    monkeypatch.setenv("FS_LICENSE", "/opt/freesurfer/license.txt")
    cfg = load_config(cfg_path)
    assert cfg.data_root == tmp_path / "data"
    assert cfg.derivatives_root == tmp_path / "derivatives"
    assert cfg.fmri.fs_license_file == "/opt/freesurfer/license.txt"


def test_load_config_env_fallback_when_yaml_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUS_DATA_ROOT", str(tmp_path / "from_env_data"))
    monkeypatch.setenv("MOUS_DERIVATIVES_ROOT", str(tmp_path / "from_env_deriv"))
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("data_root: ''\nderivatives_root: ''\n")
    cfg = load_config(cfg_path)
    assert cfg.data_root == tmp_path / "from_env_data"
    assert cfg.derivatives_root == tmp_path / "from_env_deriv"


def test_resolve_derivatives_root_precedence(monkeypatch, tmp_path):
    monkeypatch.delenv("MOUS_DERIVATIVES_ROOT", raising=False)
    assert resolve_derivatives_root({"derivatives_root": str(tmp_path / "from_defaults")}) == tmp_path / "from_defaults"

    monkeypatch.setenv("MOUS_DERIVATIVES_ROOT", str(tmp_path / "from_env"))
    assert resolve_derivatives_root({}) == tmp_path / "from_env"

    monkeypatch.delenv("MOUS_DERIVATIVES_ROOT", raising=False)
    home_default = Path.home() / "mous_derivatives"
    assert resolve_derivatives_root({}) == home_default


def test_no_user_specific_scratch_paths_in_source():
    repo_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for rel in ("src", "scripts/run_mous_driver.sbatch"):
        target = repo_root / rel
        paths = [target] if target.is_file() else target.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix in {".pyc"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "/scratch/jonathanwade" in text:
                offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, f"Hardcoded Palmetto paths found: {offenders}"
