"""Tests for m5 source-space integration with m8 reporting.

Covers:
- export_subject_payload: m5 CSV and ROI summary generation
- render_subject: verdict badge, m5 metrics, source rose section
- _verify_run_manifest: --require-m5 / --require-skip-m5 flag logic
- CLI _collect_stage_warnings: m5_error and m5_skipped_reason surfacing
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from mous_pipeline.config import PipelineConfig
from mous_pipeline.cli import _collect_stage_warnings, _verify_run_manifest
from mous_pipeline.m8_reports.export import export_subject_payload
from mous_pipeline.m8_reports.dashboard import render_subject


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path: Path) -> PipelineConfig:
    cfg = PipelineConfig()
    cfg.derivatives_root = tmp_path / "derivatives"
    return cfg


def _write_m5_npy(cfg: PipelineConfig, subject: str, n_epochs: int = 10) -> dict:
    """Write dummy m5 .npy outputs and ROI npz/json, return paths."""
    from mous_pipeline.io import stage_output_dir

    m5_dir = stage_output_dir(cfg, subject, "m5_source")
    source_dirs = np.random.uniform(0, 2 * np.pi, n_epochs)
    source_dci = np.random.uniform(0.3, 0.9, n_epochs)
    np.save(m5_dir / f"sub-{subject}_source_dirs.npy", source_dirs)
    np.save(m5_dir / f"sub-{subject}_source_dci.npy", source_dci)

    # ROI timeseries: 3 labels × n_epochs × 50 time points
    n_labels, n_times = 3, 50
    roi_matrix = np.random.randn(n_epochs, n_labels, n_times)
    roi_labels = ["lh.superiortemporal-lh", "rh.superiortemporal-rh", "lh.precentral-lh"]
    np.savez(m5_dir / f"sub-{subject}_source_roi_ts.npz", roi_matrix=roi_matrix)
    (m5_dir / f"sub-{subject}_source_roi_labels.json").write_text(json.dumps(roi_labels))

    return {
        "dirs": source_dirs,
        "dci": source_dci,
        "roi_matrix": roi_matrix,
        "roi_labels": roi_labels,
    }


def _minimal_metrics(*, verdict: str = "GO") -> dict:
    return {
        "pilot_verdict": verdict,
        "run_status": "done",
        "n_trials": 120,
        "n_zinnen": 60,
        "n_woorden": 60,
        "n_rest": 20,
        "dci_zinnen": 0.62,
        "dci_woorden": 0.55,
        "dci_rest": 0.51,
        "p_task_vs_rest": 0.02,
        "p_rayleigh_zinnen": 0.01,
        "p_rayleigh_woorden": 0.04,
        "p_woorden_vs_rest": 0.08,
        "p_zinnen_vs_woorden": 0.03,
    }


# ---------------------------------------------------------------------------
# export_subject_payload
# ---------------------------------------------------------------------------

class TestExportSubjectPayload:
    def test_basic_export_produces_core_csvs(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        subject = "A9001"
        n = 20
        export_dir = export_subject_payload(
            subject,
            cfg,
            dirs_z=np.random.uniform(0, 2 * np.pi, n),
            dirs_w=np.random.uniform(0, 2 * np.pi, n),
            dirs_r=np.random.uniform(0, 2 * np.pi, 15),
            sliding_t=np.linspace(0, 5, 50),
            sliding_dci_z=np.random.uniform(0.4, 0.8, 50),
            metrics=_minimal_metrics(),
        )
        assert (export_dir / f"{subject}_directions.csv").exists()
        assert (export_dir / f"{subject}_sliding_dci.csv").exists()
        assert (export_dir / f"{subject}_metrics.json").exists()

    def test_m5_npy_exports_source_csvs(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        subject = "A9002"
        _write_m5_npy(cfg, subject, n_epochs=8)
        n = 8
        export_dir = export_subject_payload(
            subject,
            cfg,
            dirs_z=np.random.uniform(0, 2 * np.pi, n),
            dirs_w=np.random.uniform(0, 2 * np.pi, n),
            dirs_r=np.random.uniform(0, 2 * np.pi, 6),
            sliding_t=np.linspace(0, 5, 40),
            sliding_dci_z=np.random.uniform(0.4, 0.8, 40),
            metrics={**_minimal_metrics(), "source_dci_zinnen": 0.59, "m5_n_stcs": 8},
        )
        assert (export_dir / f"{subject}_source_directions.csv").exists()
        assert (export_dir / f"{subject}_source_dci.csv").exists()

    def test_m5_roi_export_produces_summary_csv(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        subject = "A9003"
        data = _write_m5_npy(cfg, subject, n_epochs=6)
        n = 6
        export_dir = export_subject_payload(
            subject,
            cfg,
            dirs_z=np.random.uniform(0, 2 * np.pi, n),
            dirs_w=np.random.uniform(0, 2 * np.pi, n),
            dirs_r=np.random.uniform(0, 2 * np.pi, 4),
            sliding_t=np.linspace(0, 5, 30),
            sliding_dci_z=np.random.uniform(0.4, 0.8, 30),
            metrics=_minimal_metrics(),
        )
        roi_csv = export_dir / f"{subject}_source_roi_summary.csv"
        assert roi_csv.exists(), "ROI summary CSV should be written when roi npz is present"
        import pandas as pd
        df = pd.read_csv(roi_csv)
        assert set(df.columns) == {"epoch", "label", "mean_beta"}
        assert len(df) == 6 * 3  # n_epochs × n_labels
        assert set(df["label"].unique()) == set(data["roi_labels"])

    def test_no_m5_npy_skips_source_exports(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        subject = "A9004"
        n = 5
        export_dir = export_subject_payload(
            subject,
            cfg,
            dirs_z=np.random.uniform(0, 2 * np.pi, n),
            dirs_w=np.random.uniform(0, 2 * np.pi, n),
            dirs_r=np.random.uniform(0, 2 * np.pi, 3),
            sliding_t=np.linspace(0, 5, 20),
            sliding_dci_z=np.random.uniform(0.4, 0.8, 20),
            metrics=_minimal_metrics(),
        )
        assert not (export_dir / f"{subject}_source_directions.csv").exists()
        assert not (export_dir / f"{subject}_source_dci.csv").exists()
        assert not (export_dir / f"{subject}_source_roi_summary.csv").exists()

    def test_trials_df_exported_when_provided(self, tmp_path):
        import pandas as pd
        cfg = _make_cfg(tmp_path)
        subject = "A9005"
        n = 4
        trials = pd.DataFrame({"trial_id": range(n), "condition": ["ZINNEN"] * n})
        export_dir = export_subject_payload(
            subject,
            cfg,
            dirs_z=np.random.uniform(0, 2 * np.pi, n),
            dirs_w=np.random.uniform(0, 2 * np.pi, n),
            dirs_r=np.random.uniform(0, 2 * np.pi, 2),
            sliding_t=np.linspace(0, 5, 10),
            sliding_dci_z=np.random.uniform(0.4, 0.8, 10),
            metrics=_minimal_metrics(),
            trials_df=trials,
        )
        assert (export_dir / f"{subject}_trials.csv").exists()


# ---------------------------------------------------------------------------
# render_subject (dashboard)
# ---------------------------------------------------------------------------

class TestRenderSubject:
    def _run_render(self, tmp_path: Path, subject: str, metrics: dict | None = None) -> str:
        cfg = _make_cfg(tmp_path)
        if metrics is None:
            metrics = _minimal_metrics()
        payload = {
            "metrics": metrics,
            "stage_timings_s": {"m1": 0.3, "m2": 12.4, "m3": 1.1, "m8": 0.8},
            "outputs": ["/fake/output.npy"],
        }
        out = render_subject(subject, cfg, payload)
        return out.read_text()

    def test_produces_html_file(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        subject = "A9010"
        payload = {"metrics": _minimal_metrics(), "stage_timings_s": {}, "outputs": []}
        out_path = render_subject(subject, cfg, payload)
        assert out_path.exists()
        assert out_path.suffix == ".html"

    def test_verdict_badge_present_and_colored(self, tmp_path):
        html = self._run_render(tmp_path, "A9011", metrics={**_minimal_metrics(), "pilot_verdict": "GO"})
        assert "GO" in html
        assert "#2e7d32" in html  # green

    def test_verdict_no_go_uses_red(self, tmp_path):
        html = self._run_render(tmp_path, "A9012", metrics={**_minimal_metrics(), "pilot_verdict": "NO-GO"})
        assert "#b71c1c" in html

    def test_verdict_marginal_uses_amber(self, tmp_path):
        html = self._run_render(tmp_path, "A9013", metrics={**_minimal_metrics(), "pilot_verdict": "MARGINAL"})
        assert "#e65100" in html

    def test_m5_metrics_appear_in_table(self, tmp_path):
        metrics = {
            **_minimal_metrics(),
            "source_dci_zinnen": 0.61,
            "m5_n_labels": 10,
            "m5_n_stcs": 60,
        }
        html = self._run_render(tmp_path, "A9014", metrics=metrics)
        assert "Source DCI" in html
        assert "ROI labels" in html

    def test_m5_error_banner_shown(self, tmp_path):
        metrics = {**_minimal_metrics(), "m5_error": "fsaverage not found"}
        html = self._run_render(tmp_path, "A9015", metrics=metrics)
        assert "m5 error" in html.lower()
        assert "fsaverage not found" in html

    def test_m5_skipped_banner_shown(self, tmp_path):
        metrics = {**_minimal_metrics(), "m5_skipped_reason": "source.subjects_dir not configured"}
        html = self._run_render(tmp_path, "A9016", metrics=metrics)
        assert "m5 skipped" in html.lower()

    def test_source_rose_section_present_when_npy_exists(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        subject = "A9017"
        _write_m5_npy(cfg, subject, n_epochs=10)
        metrics = {**_minimal_metrics(), "source_dci_zinnen": 0.59, "m5_n_stcs": 10}
        payload = {"metrics": metrics, "stage_timings_s": {}, "outputs": []}
        html = render_subject(subject, cfg, payload).read_text()
        assert "Source-space" in html

    def test_timing_bars_present(self, tmp_path):
        html = self._run_render(tmp_path, "A9018")
        assert "Stage timings" in html
        assert "m2" in html

    def test_outputs_list_present(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        subject = "A9019"
        payload = {
            "metrics": _minimal_metrics(),
            "stage_timings_s": {},
            "outputs": ["/some/path/output.npy"],
        }
        html = render_subject(subject, cfg, payload).read_text()
        assert "output.npy" in html

    def test_raw_payload_collapsed_in_details(self, tmp_path):
        html = self._run_render(tmp_path, "A9020")
        assert "<details>" in html
        assert "Raw payload" in html


# ---------------------------------------------------------------------------
# _verify_run_manifest
# ---------------------------------------------------------------------------

class TestVerifyRunManifest:
    def _manifest(self, **metrics_overrides) -> dict:
        base_metrics = {
            "run_status": "done",
            "skipped_stages": [],
        }
        base_metrics.update(metrics_overrides)
        return {"metrics": base_metrics, "outputs": ["some_output.npy"]}

    def test_valid_manifest_passes(self):
        assert _verify_run_manifest(self._manifest()) == []

    def test_bad_run_status_fails(self):
        errs = _verify_run_manifest(self._manifest(run_status="failed"))
        assert any("run_status" in e for e in errs)

    def test_require_skip_m5_passes_when_skipped(self):
        m = self._manifest(skipped_stages=["m5"])
        assert _verify_run_manifest(m, require_skip_m5=True) == []

    def test_require_skip_m5_fails_when_not_skipped(self):
        errs = _verify_run_manifest(self._manifest(skipped_stages=[]), require_skip_m5=True)
        assert any("skipped_stages" in e for e in errs)

    def test_require_m5_passes_when_source_outputs_present(self):
        m = self._manifest(
            skipped_stages=[],
            source_dci_zinnen=0.61,
            m5_n_stcs=60,
        )
        assert _verify_run_manifest(m, require_m5=True) == []

    def test_require_m5_fails_when_skipped(self):
        m = self._manifest(skipped_stages=["m5"])
        errs = _verify_run_manifest(m, require_m5=True)
        assert any("not be skipped" in e or "must not" in e for e in errs)

    def test_require_m5_fails_when_m5_error_present(self):
        m = self._manifest(skipped_stages=[], m5_error="BEM failed", source_dci_zinnen=None, m5_n_stcs=None)
        errs = _verify_run_manifest(m, require_m5=True)
        assert any("error" in e.lower() for e in errs)

    def test_require_m5_fails_when_no_source_outputs(self):
        m = self._manifest(skipped_stages=[])
        errs = _verify_run_manifest(m, require_m5=True)
        assert any("source_dci_zinnen" in e or "no source-space" in e.lower() for e in errs)

    def test_require_m5_and_skip_m5_are_mutually_exclusive_in_effect(self):
        """Manifests cannot satisfy both require_m5 and require_skip_m5."""
        m_skipped = self._manifest(skipped_stages=["m5"])
        m_ran = self._manifest(skipped_stages=[], source_dci_zinnen=0.6, m5_n_stcs=60)
        assert _verify_run_manifest(m_skipped, require_skip_m5=True) == []
        assert _verify_run_manifest(m_ran, require_m5=True) == []
        # If both flags set, one will always fire
        errs = _verify_run_manifest(m_skipped, require_skip_m5=True, require_m5=True)
        assert len(errs) > 0

    def test_strict_mode_catches_m10_error(self):
        m = self._manifest(m10_error="NiBabel not found")
        errs = _verify_run_manifest(m, strict_mode=True)
        assert any("m10_error" in e for e in errs)

    def test_empty_outputs_list_is_tolerated(self):
        # verify-run was relaxed (b5eecf0) to tolerate manifests without
        # top-level outputs so successful runs are not falsely flagged.
        payload = {"metrics": {"run_status": "done", "skipped_stages": []}, "outputs": []}
        errs = _verify_run_manifest(payload)
        assert not any("outputs" in e for e in errs)


# ---------------------------------------------------------------------------
# _collect_stage_warnings
# ---------------------------------------------------------------------------

class TestCollectStageWarnings:
    def test_no_warnings_for_clean_metrics(self):
        assert _collect_stage_warnings({"run_status": "done"}) == []

    def test_m5_error_surfaces_warning(self):
        warnings = _collect_stage_warnings({"m5_error": "fsaverage missing"})
        assert len(warnings) == 1
        assert "m5" in warnings[0].lower()
        assert "fsaverage missing" in warnings[0]

    def test_m5_skipped_reason_surfaces_warning(self):
        warnings = _collect_stage_warnings({"m5_skipped_reason": "subjects_dir not set"})
        assert len(warnings) == 1
        assert "m5 skipped" in warnings[0].lower()

    def test_m10_error_surfaces_warning(self):
        warnings = _collect_stage_warnings({"m10_error": "NiBabel error"})
        assert any("m10" in w for w in warnings)

    def test_multiple_stage_warnings_all_returned(self):
        warnings = _collect_stage_warnings({
            "m5_error": "BEM failed",
            "m10_error": "BOLD not found",
            "m11_skipped_reason": "No MEG-fMRI join",
        })
        assert len(warnings) == 3

    def test_m5_error_and_skip_both_shown(self):
        """Both m5_error and m5_skipped_reason can coexist (edge case)."""
        warnings = _collect_stage_warnings({
            "m5_error": "crash",
            "m5_skipped_reason": "also skipped",
        })
        assert len(warnings) == 2
