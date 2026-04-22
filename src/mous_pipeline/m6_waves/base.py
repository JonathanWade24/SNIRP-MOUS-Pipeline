"""Module 6 detector interface and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod


DETECTOR_REGISTRY: dict[str, type["WaveDetector"]] = {}


def register(name: str):
    def _decorator(cls):
        DETECTOR_REGISTRY[name] = cls
        return cls

    return _decorator


class WaveDetector(ABC):
    name: str = "base"
    required_inputs: set[str] = set()

    @abstractmethod
    def detect(self, features):
        raise NotImplementedError
