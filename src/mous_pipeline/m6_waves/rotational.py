"""Module 6D rotational detector stub."""

from .base import WaveDetector, register


@register("rotational")
class RotationalDetector(WaveDetector):
    name = "rotational"

    def detect(self, features):
        raise NotImplementedError("Module 6D is a declared TODO — see design brief §7 Module 6D.")
