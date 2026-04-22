"""Pilot gating criteria."""

from __future__ import annotations


def evaluate_pilot_gate(metrics: dict) -> dict:
    criteria = {
        "min_zinnen_epochs": metrics.get("n_zinnen", 0) >= 50,
        "task_gt_rest": metrics.get("dci_zinnen", 0.0) > metrics.get("dci_rest", 0.0),
        "dci_significant": metrics.get("p_task_vs_rest", 1.0) < 0.05,
        "task_nonuniform_direction": metrics.get("p_rayleigh_zinnen", 1.0) < 0.05,
    }
    n_pass = sum(criteria.values())
    verdict = "GO" if n_pass == 4 else "MARGINAL" if n_pass >= 2 else "NO-GO"
    return {"criteria": criteria, "n_pass": n_pass, "verdict": verdict}
