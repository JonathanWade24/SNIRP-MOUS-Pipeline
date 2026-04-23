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
class SourceConfig:
    subjects_dir: str = ""
    use_fsaverage: bool = True
    beamformer: str = "lcmv"
    spacing: str = "oct6"
    trans: str = "fsaverage"
    conductivity: tuple[float, ...] = (0.3,)
    reg: float = 0.05
    pick_ori: str = "max-power"
    weight_norm: str = "unit-noise-gain"


@dataclass
class FmriConfig:
    bold_path: str = ""
    tr: float = 2.0
    atlas: str = "glasser"
    roi: str = "L_TE1a"
    fmriprep_container: str = ""
    fmriprep_output: str = ""
    skip_fmriprep: bool = True


@dataclass
class WaveValidationConfig:
    enabled: bool = False
    n_trials: int = 60
    snr: float = 1.0
    random_state: int = 42


@dataclass
class PipelineConfig:
    data_root: Path = Path(".")
    derivatives_root: Path = Path("derivatives/mous_pipeline")
    subjects: list[str] = field(default_factory=list)
    paths: dict[str, str] = field(default_factory=dict)
    rdr: RdrConfig = field(default_factory=RdrConfig)
    source: SourceConfig = field(default_factory=SourceConfig)
    fmri: FmriConfig = field(default_factory=FmriConfig)
    wave_validation: WaveValidationConfig = field(default_factory=WaveValidationConfig)
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
    source_raw = raw.get("source", {})
    conductivity_raw = source_raw.get("conductivity", [0.3])
    source = SourceConfig(
        subjects_dir=str(source_raw.get("subjects_dir", "")),
        use_fsaverage=bool(source_raw.get("use_fsaverage", True)),
        beamformer=str(source_raw.get("beamformer", "lcmv")),
        spacing=str(source_raw.get("spacing", "oct6")),
        trans=str(source_raw.get("trans", "fsaverage")),
        conductivity=tuple(float(x) for x in conductivity_raw),
        reg=float(source_raw.get("reg", 0.05)),
        pick_ori=str(source_raw.get("pick_ori", "max-power")),
        weight_norm=str(source_raw.get("weight_norm", "unit-noise-gain")),
    )
    fmri_raw = raw.get("fmri", {})
    fmri = FmriConfig(
        bold_path=str(fmri_raw.get("bold_path", "")),
        tr=float(fmri_raw.get("tr", 2.0)),
        atlas=str(fmri_raw.get("atlas", "glasser")),
        roi=str(fmri_raw.get("roi", "L_TE1a")),
        fmriprep_container=str(fmri_raw.get("fmriprep_container", "")),
        fmriprep_output=str(fmri_raw.get("fmriprep_output", "")),
        skip_fmriprep=bool(fmri_raw.get("skip_fmriprep", True)),
    )
    wv_raw = raw.get("wave_validation", {})
    wave_validation = WaveValidationConfig(
        enabled=bool(wv_raw.get("enabled", False)),
        n_trials=int(wv_raw.get("n_trials", 60)),
        snr=float(wv_raw.get("snr", 1.0)),
        random_state=int(wv_raw.get("random_state", 42)),
    )

    return PipelineConfig(
        data_root=Path(raw.get("data_root", ".")).expanduser(),
        derivatives_root=Path(raw.get("derivatives_root", "derivatives/mous_pipeline")).expanduser(),
        subjects=raw.get("subjects", []),
        paths=raw.get("paths", {}),
        rdr=rdr,
        source=source,
        fmri=fmri,
        wave_validation=wave_validation,
        preprocess=preprocess,
        epoching=epoching,
        features=features,
        pipeline=raw.get("pipeline", {}),
    )
