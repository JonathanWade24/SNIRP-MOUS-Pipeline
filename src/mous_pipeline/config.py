"""Configuration models and YAML loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PreprocessConfig:
    backend: str = "inhouse"
    notch_freqs: list[float] = field(default_factory=lambda: [50.0, 100.0, 150.0])
    resample_hz: float = 300.0
    ica_n_components: int = 40
    ecg_threshold: float = 0.9
    ecg_max_components: int = 3


@dataclass
class EpochingConfig:
    tmin: float = -0.5
    tmax: float = 3.0
    baseline: tuple[float, float] = (-0.5, 0.0)
    min_trials_per_condition: int = 50


@dataclass
class FeatureConfig:
    bands: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "theta": (4.0, 8.0),
            "alpha": (8.0, 13.0),
            "beta": (13.0, 30.0),
            "gamma": (30.0, 80.0),
        }
    )


@dataclass
class RdrConfig:
    """Radboud Data Repository: subject folders live under collection_path on WebDAV."""

    collection_path: str = ""
    notes: str = ""


@dataclass
class PipelineConfig:
    data_root: Path = Path(".")
    derivatives_root: Path = Path("derivatives/mous_pipeline")
    subjects: list[str] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)
    rdr: RdrConfig = field(default_factory=RdrConfig)
    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    epoching: EpochingConfig = field(default_factory=EpochingConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    pipeline: dict[str, Any] = field(default_factory=dict)


def _to_tuple_bands(bands: dict[str, list[float] | tuple[float, float]]) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for key, vals in bands.items():
        out[key] = (float(vals[0]), float(vals[1]))
    return out


def load_config(path: str | Path) -> PipelineConfig:
    """Load YAML config into typed PipelineConfig."""
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text()) or {}

    preprocess = PreprocessConfig(**raw.get("preprocess", {}))
    ep_raw = raw.get("epoching", {})
    if "baseline" in ep_raw and isinstance(ep_raw["baseline"], list):
        ep_raw["baseline"] = tuple(ep_raw["baseline"])
    epoching = EpochingConfig(**ep_raw)

    feat_raw = raw.get("features", {})
    bands = _to_tuple_bands(feat_raw.get("bands", FeatureConfig().bands))
    features = FeatureConfig(bands=bands)

    rdr_raw = raw.get("rdr", {})
    rdr = RdrConfig(
        collection_path=str(rdr_raw.get("collection_path", "")),
        notes=str(rdr_raw.get("notes", "")),
    )

    return PipelineConfig(
        data_root=Path(raw.get("data_root", ".")),
        derivatives_root=Path(raw.get("derivatives_root", "derivatives/mous_pipeline")),
        subjects=raw.get("subjects", []),
        paths=raw.get("paths", {}),
        rdr=rdr,
        preprocess=preprocess,
        epoching=epoching,
        features=features,
        pipeline=raw.get("pipeline", {}),
    )
