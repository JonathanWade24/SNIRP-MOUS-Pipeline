"""Module 9 pipeline contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class StageResult:
    name: str
    outputs: list[Path] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class Stage(Protocol):
    name: str

    def inputs(self, cfg, subject: str) -> list[Path]: ...

    def outputs(self, cfg, subject: str) -> list[Path]: ...

    def run(self, cfg, subject: str) -> StageResult: ...

    def qa(self, cfg, subject: str) -> dict[str, Any]: ...


@dataclass
class Pipeline:
    stages: list[Stage]

    def run(self, cfg, subject: str, only: set[str] | None = None) -> list[StageResult]:
        results: list[StageResult] = []
        for stage in self.stages:
            if only and stage.name not in only:
                continue
            results.append(stage.run(cfg, subject))
        return results
