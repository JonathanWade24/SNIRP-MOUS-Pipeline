#!/usr/bin/env python3
"""Write Aim 3 null summary artifacts from run manifests/group summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def _collect_metrics(derivatives_root: Path) -> list[dict]:
    metrics: list[dict] = []
    for mf in sorted(derivatives_root.glob("*/m9_orchestration/*_run_manifest.json")):
        try:
            payload = json.loads(mf.read_text())
            met = payload.get("metrics", {})
            if met:
                sid = mf.parts[-3].removeprefix("sub-")
                met["_subject_id"] = sid
                metrics.append(met)
        except Exception:
            continue
    return metrics


def _arr(metrics: list[dict], key: str) -> np.ndarray:
    vals = [float(m[key]) for m in metrics if key in m and m[key] is not None]
    return np.asarray(vals, dtype=float) if vals else np.asarray([], dtype=float)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Aim 3 null outputs.")
    parser.add_argument("--derivatives-root", required=True, help="Path to derivatives/mous_pipeline-like root.")
    parser.add_argument("--out-md", required=True, help="Output markdown report path.")
    parser.add_argument("--out-json", required=True, help="Output JSON summary path.")
    args = parser.parse_args()

    droot = Path(args.derivatives_root).expanduser().resolve()
    metrics = _collect_metrics(droot)
    if not metrics:
        raise SystemExit("No subject run manifests found.")

    dci_z = _arr(metrics, "dci_zinnen")
    dci_w = _arr(metrics, "dci_woorden")
    dci_r = _arr(metrics, "dci_rest")
    p_tr = _arr(metrics, "p_task_vs_rest")
    p_zw = _arr(metrics, "p_zinnen_vs_woorden")
    subjects = sorted({str(m.get("_subject_id", "unknown")) for m in metrics})

    summary = {
        "n_subjects": len(subjects),
        "subjects": subjects,
        "dci_zinnen_mean": float(np.mean(dci_z)) if dci_z.size else None,
        "dci_woorden_mean": float(np.mean(dci_w)) if dci_w.size else None,
        "dci_rest_mean": float(np.mean(dci_r)) if dci_r.size else None,
        "dci_zinnen_range": [float(np.min(dci_z)), float(np.max(dci_z))] if dci_z.size else None,
        "dci_woorden_range": [float(np.min(dci_w)), float(np.max(dci_w))] if dci_w.size else None,
        "dci_rest_range": [float(np.min(dci_r)), float(np.max(dci_r))] if dci_r.size else None,
        "p_task_vs_rest_median": float(np.median(p_tr)) if p_tr.size else None,
        "p_task_vs_rest_above_0_1": int(np.sum(p_tr > 0.1)) if p_tr.size else 0,
        "p_task_vs_rest_n": int(p_tr.size),
        "p_zinnen_vs_woorden_median": float(np.median(p_zw)) if p_zw.size else None,
    }

    out_json = Path(args.out_json).expanduser().resolve()
    out_md = Path(args.out_md).expanduser().resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2))

    md = f"""# Aim 3 Null Summary

- Subjects analyzed: {summary["n_subjects"]}
- DCI (ZINNEN) mean/range: {summary["dci_zinnen_mean"]} / {summary["dci_zinnen_range"]}
- DCI (WOORDEN) mean/range: {summary["dci_woorden_mean"]} / {summary["dci_woorden_range"]}
- DCI (REST) mean/range: {summary["dci_rest_mean"]} / {summary["dci_rest_range"]}
- p_task_vs_rest median: {summary["p_task_vs_rest_median"]} (n={summary["p_task_vs_rest_n"]}, >0.1 count={summary["p_task_vs_rest_above_0_1"]})
- p_zinnen_vs_woorden median: {summary["p_zinnen_vs_woorden_median"]}

Interpretation: if DCI stays low and p-values remain mostly > 0.1, this supports a stable sensor-level null for task-modulated directional coherence in this dataset.
"""
    out_md.write_text(md)
    print(f"Wrote {out_md}")
    print(f"Wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
