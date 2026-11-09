"""Manual output gain with smoothing and a peak limiter; no lookahead buffer."""
import math
import numpy as np

MIN_GAIN_DB = 0
MAX_GAIN_DB = 18
CEILING = .98


def clamp_gain(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.
    return min(MAX_GAIN_DB, max(MIN_GAIN_DB, value)) if math.isfinite(value) else 0.


class OutputGain:
    def __init__(self, gain_db: float = 0.0, rate: int = 16000):
        self.rate = rate
        self.configure(gain_db)
        self.gain = self.target
        self.limiter = 1.0
        self._steps = np.arange(1, max(1, round(rate * 0.016)) + 1, dtype=np.float32)
        self._smooth = np.exp(-self._steps / (rate * 0.02)).astype(np.float32)
        self._release = np.exp(-self._steps / (rate * 0.05)).astype(np.float32)
        # P0-2: 1.5ms soft attack slope
        self._attack = np.exp(-self._steps / (rate * 0.0015)).astype(np.float32)

    def configure(self, gain_db: float):
        self.gain_db = clamp_gain(gain_db)
        self.target = 10.0 ** (self.gain_db / 20.0)

    def process(self, pcm: np.ndarray) -> np.ndarray:
        if not len(pcm):
            return pcm
        result = np.empty_like(pcm)
        hop = len(self._steps)
        for start in range(0, len(pcm), hop):
            part = pcm[start:start + hop]
            n = len(part)
            if abs(self.gain - self.target) < 1e-06:
                self.gain = self.target
                y = part * self.gain
            else:
                ramp = self.target + (self.gain - self.target) * self._smooth[:n]
                y = part * ramp
                self.gain = float(ramp[-1])
            peak = float(np.max(np.abs(y)))
            allowed = min(1.0, CEILING / peak) if peak else 1.0
            if allowed <= self.limiter:
                # P0-2: Soft Attack curve to eliminate step clicks
                ramp = allowed + (self.limiter - allowed) * self._attack[:n]
                y = y * ramp
                self.limiter = float(ramp[-1])
            else:
                ramp = allowed + (self.limiter - allowed) * self._release[:n]
                y = y * ramp
                self.limiter = float(ramp[-1])

            # P0-2: Soft-knee saturation above 0.90 to smoothly cap at CEILING (0.98)
            mask = np.abs(y) > 0.90
            if np.any(mask):
                y_sign = np.sign(y[mask])
                y_abs = np.abs(y[mask])
                y[mask] = y_sign * (0.90 + 0.08 * np.tanh((y_abs - 0.90) / 0.08))
            np.clip(y, -CEILING, CEILING, out=result[start:start + n])
        return result

