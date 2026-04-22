"""Module 6C flow-field detector stub."""

from .base import WaveDetector, register


@register("flow_field")
class FlowFieldDetector(WaveDetector):
    name = "flow_field"

    def detect(self, features):
        raise NotImplementedError("Module 6C is a declared TODO — see design brief §7 Module 6C.")
