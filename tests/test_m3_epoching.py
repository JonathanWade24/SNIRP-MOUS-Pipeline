import pytest

mne = pytest.importorskip("mne")

from mous_pipeline.config import PipelineConfig
from mous_pipeline.m0_intake.naming import rest_ds, task_ds
from mous_pipeline.m1_events.parse import parse_events
from mous_pipeline.m2_preprocess.filter import apply_band, apply_notch_and_resample
from mous_pipeline.m2_preprocess.ica import fit_and_apply
from mous_pipeline.m3_epoching.rest import make_pseudo_epochs
from mous_pipeline.m3_epoching.task import make_epochs


def test_epoch_counts_match_pilot(repo_root):
    task_path = task_ds("A2002", repo_root)
    rest_path = rest_ds("A2002", repo_root)
    events_path = repo_root / "sub-A2002" / "meg" / "sub-A2002_task-auditory_events.tsv"
    if not task_path.exists() or not rest_path.exists() or not events_path.exists():
        pytest.skip("Raw pilot data not available; skipping heavy epoching test.")

    cfg = PipelineConfig(data_root=repo_root)
    trials = parse_events(str(events_path))

    raw = mne.io.read_raw_ctf(str(task_path), preload=True, system_clock="truncate", verbose="WARNING")
    raw.apply_gradient_compensation(3)
    raw = apply_notch_and_resample(raw, cfg)
    raw, ica = fit_and_apply(raw, cfg)
    raw = apply_band(raw, 13, 30)
    epochs = make_epochs(raw, trials, cfg)

    raw_rest = mne.io.read_raw_ctf(str(rest_path), preload=True, system_clock="truncate", verbose="WARNING")
    raw_rest.apply_gradient_compensation(3)
    raw_rest = apply_notch_and_resample(raw_rest, cfg)
    ica.apply(raw_rest)
    raw_rest = apply_band(raw_rest, 13, 30)
    rest_epochs = make_pseudo_epochs(raw_rest, cfg.epoching.tmax - cfg.epoching.tmin)

    assert len(epochs["ZINNEN"]) == 110
    assert len(epochs["WOORDEN"]) == 110
    assert len(rest_epochs) == 86
