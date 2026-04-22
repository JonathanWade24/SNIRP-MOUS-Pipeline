"""Module 6B frequency-domain detector stub."""

from .base import WaveDetector, register


@register("fft2d")
class FFT2DDetector(WaveDetector):
    name = "fft2d"

    def detect(self, features):
        raise NotImplementedError("Module 6B is a declared TODO — see design brief §7 Module 6B.")
