"""Raw microphone electrical distortion, with 10% less drive than battle v1."""
import numpy as np

CEILING = 0.98
DRIVE = (10.0 ** (36.0 / 20.0)) * .9
EFFECT_STRENGTH = .9


class BattleEffect:
    def __init__(self, rate):
        self.rate = rate
        self.position = 0

    def process(self, pcm):
        if not len(pcm):
            return pcm.copy()
        t = (self.position + np.arange(len(pcm))) / self.rate
        self.position += len(pcm)
        rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
        if rms < 1e-5:
            return np.zeros_like(pcm)
        driven = pcm * DRIVE
        # Quantization and folding tear the waveform. Multiplication adds no idle hum.
        bounded = np.clip(driven, -3.0, 3.0)
        quantized = np.round(bounded * 12.0) / 12.0
        crushed = bounded + EFFECT_STRENGTH * (quantized - bounded)
        folded = (2.0 / np.pi) * np.arcsin(np.sin(crushed * (3.8 * EFFECT_STRENGTH)))
        carrier = .60 + EFFECT_STRENGTH * (
            .30 * np.sin(2 * np.pi * 113 * t) + .20 * np.sin(2 * np.pi * 1733 * t))
        y = .22 * driven + .78 * folded * carrier
        y -= np.mean(y)
        shaped_rms = float(np.sqrt(np.mean(y ** 2)))
        # Do not let added modulation exceed the previous clipped voice level.
        reference = np.clip(driven, -CEILING, CEILING)
        reference_rms = float(np.sqrt(np.mean(reference.astype(np.float64) ** 2)))
        y *= min(1.0, reference_rms / max(shaped_rms, 1e-12))
        return np.clip(y, -CEILING, CEILING).astype(pcm.dtype)
