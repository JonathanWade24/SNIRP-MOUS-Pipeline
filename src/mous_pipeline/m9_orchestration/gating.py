"""Module 9 gating wrapper."""

from __future__ import annotations

from ..pilot_gating import evaluate_pilot_gate


class PilotGate:
    def evaluate(self, metrics: dict) -> dict:
        return evaluate_pilot_gate(metrics)
