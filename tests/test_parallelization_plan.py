import os
import subprocess
import sys
from pathlib import Path

import pytest

from mous_pipeline.m9_orchestration.memory_probe import StageRSSProbe, current_rss_bytes
from mous_pipeline.m9_orchestration.parallelization_plan import (
    dag_parallelism_report,
    intra_subject_pilot_protocol,
    recommend_subject_parallelism,
)
from mous_pipeline.m9_orchestration.runner import run_subject
from mous_pipeline.config import PipelineConfig
from mous_pipeline.stage_dependencies import parallel_execution_fronts

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def test_parallel_execution_fronts_full_pipeline():
    fronts = parallel_execution_fronts()
    assert fronts[0] == ["m1"]
    assert set(fronts[1]) == {"m2"}
    assert set(fronts[2]) == {"m3"}
    assert set(fronts[3]) == {"m4", "m4_trial", "m5", "m6a"}
    # m7 only needs m6a; m6_extra needs m4; m10 needs m4_trial; m12 needs m6a — all satisfied after front 3.
    assert set(fronts[4]) == {"m6_extra", "m10", "m12", "m7"}
    # m8 and m9 both depend only on m7; m11 depends on m10 — all ready after front 4.
    assert set(fronts[5]) == {"m11", "m8", "m9"}
    assert len(fronts) == 6


def test_parallel_execution_fronts_invalid_selection_raises():
    with pytest.raises(ValueError, match="m4 requires m3"):
        parallel_execution_fronts(["m4"])


def test_recommend_subject_parallelism():
    out = recommend_subject_parallelism(
        total_ram_gb=32.0,
        os_reserve_gb=8.0,
        peak_rss_gb=10.0,
        n_cpus=6,
    )
    assert out["n_subjects_max_conservative"] == 2
    assert out["suggested_omp_num_threads_per_process"] == 3


def test_recommend_subject_parallelism_zero_subjects():
    out = recommend_subject_parallelism(
        total_ram_gb=32.0,
        os_reserve_gb=8.0,
        peak_rss_gb=30.0,
        n_cpus=6,
    )
    assert out["n_subjects_max_conservative"] == 0


def test_dag_parallelism_report_has_fronts():
    r = dag_parallelism_report()
    assert r["max_front_width"] == 4
    assert any(set(f) == {"m4", "m4_trial", "m5", "m6a"} for f in r["parallel_fronts"])
    assert any(set(f) == {"m6_extra", "m10", "m12", "m7"} for f in r["parallel_fronts"])


def test_intra_subject_pilot_protocol_keys():
    p = intra_subject_pilot_protocol()
    assert "goal" in p and "steps" in p


def test_stage_rss_probe_record():
    probe = StageRSSProbe(live_log_path=None, sample_interval_s=0.0)
    probe.record("start", "m1")
    if current_rss_bytes() is not None:
        probe.record("done", "m1")
        s = probe.summary()
        assert "per_stage_mb" in s
        assert "m1" in s["per_stage_mb"]


def test_run_subject_dry_run_memory_profile_no_probe():
    cfg = PipelineConfig()
    result = run_subject("A9999", cfg, dry_run=True, memory_profile=True)
    assert result.metrics.get("dry_run") is True
    assert "memory_rss_summary" not in result.metrics


def test_cli_parallelization_plan_smoke():
    proc = subprocess.run(
        [sys.executable, "-m", "mous_pipeline.cli", "parallelization-plan"],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
    )
    assert "Front 1" in proc.stdout
    assert "m4" in proc.stdout


def test_cli_parallelization_plan_with_peak_rss():
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mous_pipeline.cli",
            "parallelization-plan",
            "--peak-rss-gb",
            "12",
            "--os-reserve-gb",
            "8",
            "--total-ram-gb",
            "32",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
    )
    assert '"n_subjects_max_conservative": 2' in proc.stdout
    assert "max_front_width" in proc.stdout
