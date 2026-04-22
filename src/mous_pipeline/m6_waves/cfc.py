"""Module 6E cross-frequency detector stub."""

from .base import WaveDetector, register


@register("cfc")
class CFCDetector(WaveDetector):
    name = "cfc"

    def detect(self, features):
        raise NotImplementedError("Module 6E is a declared TODO — see design brief §7 Module 6E.")
