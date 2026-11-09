"""Manual audio detection threshold and a click-free output gate."""
import math
import numpy as np


MIN_FLOOR_DB = -90.
MAX_FLOOR_DB = -20.


def clamp_floor(value, default=-60.):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return min(MAX_FLOOR_DB, max(MIN_FLOOR_DB, value)) if math.isfinite(value) else default


class AudioGate:
    HOLD_SECONDS = 0.15
    HYSTERESIS_DB = 6.0
    ATTACK_SECONDS = 0.003
    RELEASE_SECONDS = 0.02

    def __init__(self, threshold_db: float = -60.0, purity: str = 'balanced'):
        self.manual_db = clamp_floor(threshold_db)
        self.purity = purity if purity in ('natural', 'balanced', 'ultra') else 'balanced'
        self.open = False
        self.hold_left = 0
        self.gain = 0.0
        self._ramp = np.arange(1, 257, dtype=np.float32)
        self._attack_exp = np.exp(-self._ramp / (self.ATTACK_SECONDS * 16000)).astype(np.float32)
        self._release_exp = np.exp(-self._ramp / (self.RELEASE_SECONDS * 16000)).astype(np.float32)
        self._hold_samples = round(self.HOLD_SECONDS * 16000)
        self._prev_in_sq = 1e-12
        self._ambient_in_sq = None
        self._prev_raw = np.zeros(256, dtype=np.float32)
        self._noise_mag = np.full(257, 1e-4, dtype=np.float32)
        self.last_supp_db = 0.0
        self.last_db = -99.0

        # Filters for 3 purity modes (512-pt FFT @ 16kHz, 31.25Hz / bin)
        # 1. Natural: 80Hz HP, 7.6kHz LP
        self._mask_natural = np.ones(257, dtype=np.float32)
        self._mask_natural[0] = 0.0
        self._mask_natural[1] = 0.05
        self._mask_natural[2] = 0.35
        self._mask_natural[3] = 0.85
        self._mask_natural[244:] = np.linspace(1.0, 0.0, 13, dtype=np.float32)

        # 2. Balanced: 95Hz HP, 7.2kHz LP
        self._mask_balanced = np.ones(257, dtype=np.float32)
        self._mask_balanced[0] = 0.0
        self._mask_balanced[1] = 0.02
        self._mask_balanced[2] = 0.15
        self._mask_balanced[3] = 0.65
        self._mask_balanced[231:] = np.linspace(1.0, 0.0, 26, dtype=np.float32)

        # 3. Ultra: 110Hz HP, 6.8kHz LP
        self._mask_ultra = np.ones(257, dtype=np.float32)
        self._mask_ultra[0] = 0.0
        self._mask_ultra[1] = 0.0
        self._mask_ultra[2] = 0.05
        self._mask_ultra[3] = 0.30
        self._mask_ultra[4] = 0.80
        self._mask_ultra[218:] = np.linspace(1.0, 0.0, 39, dtype=np.float32)

    @property
    def threshold_db(self):
        return self.manual_db

    def configure(self, threshold_db: float | None = None, purity: str | None = None):
        if threshold_db is not None:
            self.manual_db = clamp_floor(threshold_db)
        if purity is not None and purity in ('natural', 'balanced', 'ultra'):
            self.purity = purity

    def status(self):
        return {'threshold_db': self.threshold_db, 'open': self.open, 'gain': self.gain, 'purity': self.purity}

    def _postfilter(self, part: np.ndarray, supp_db: float) -> np.ndarray:
        if len(part) != 256:
            return part
        buf = np.concatenate((self._prev_raw, part))
        self._prev_raw = part.copy()
        spec = np.fft.rfft(buf)
        mag = np.abs(spec).astype(np.float32)
        if not self.open:
            self._noise_mag = 0.90 * self._noise_mag + 0.10 * mag
        else:
            quiet = mag < (self._noise_mag * 1.8)
            self._noise_mag = np.where(quiet, 0.95 * self._noise_mag + 0.05 * mag, 0.998 * self._noise_mag)

        # Mode differentiated Wiener oversubtraction alpha & floor gain
        if self.purity == 'natural':
            alpha = 1.2 if supp_db < 6.0 else min(3.5, 1.2 + (supp_db - 6.0) * 0.25)
            floor_gain = 0.15 if (self.open and supp_db < 8.0) else 0.0
            mask = self._mask_natural
        elif self.purity == 'ultra':
            alpha = 1.8 if supp_db < 5.0 else min(5.0, 1.8 + (supp_db - 5.0) * 0.35)
            floor_gain = 0.03 if (self.open and supp_db < 7.0) else 0.0
            mask = self._mask_ultra
        else:  # balanced
            alpha = 1.5 if supp_db < 5.5 else min(4.2, 1.5 + (supp_db - 5.5) * 0.30)
            floor_gain = 0.08 if (self.open and supp_db < 7.5) else 0.0
            mask = self._mask_balanced

        snr_prio = np.maximum(0.0, (mag ** 2) - (alpha * self._noise_mag) ** 2)
        wiener = snr_prio / (snr_prio + (self._noise_mag ** 2) + 1e-12)
        wiener[1:-1] = 0.25 * wiener[:-2] + 0.50 * wiener[1:-1] + 0.25 * wiener[2:]
        wiener = np.maximum(floor_gain, wiener).astype(np.float32)
        y512 = np.fft.irfft(spec * (wiener * mask), n=512).astype(np.float32)
        return y512[256:].copy()

    def process(self, pcm: np.ndarray, *, in_rms: float | None = None) -> np.ndarray:
        if not len(pcm):
            return pcm
        result = np.empty_like(pcm)
        in_sq = (float(in_rms) ** 2) if in_rms is not None else None

        for start in range(0, len(pcm), 256):
            part = pcm[start:start + 256]
            n = len(part)
            out_sq = float(np.dot(part, part)) / n
            rms = math.sqrt(out_sq)
            db = 10.0 * math.log10(max(out_sq, 1e-24))
            self.last_db = db

            if self.purity == 'ultra' and in_sq is not None:
                ref_in_sq = max(in_sq, self._prev_in_sq)
                self._prev_in_sq = in_sq
                raw_supp_db = 10.0 * math.log10(max(ref_in_sq, 1e-24) / max(out_sq, 1e-24))
                if self._ambient_in_sq is None:
                    self._ambient_in_sq = in_sq if raw_supp_db > 25.0 else (in_sq * 0.01)
                elif in_sq < self._ambient_in_sq:
                    self._ambient_in_sq = 0.70 * self._ambient_in_sq + 0.30 * in_sq
                elif raw_supp_db > 25.0 and not self.open and in_sq < self._ambient_in_sq * 2.5:
                    self._ambient_in_sq = 0.90 * self._ambient_in_sq + 0.10 * in_sq
                eff_in_sq = max(ref_in_sq * 0.03, ref_in_sq - 0.97 * self._ambient_in_sq)
                supp_db = max(0.0, 10.0 * math.log10(max(eff_in_sq, 1e-24) / max(out_sq, 1e-24)))
            else:
                supp_db = 0.0
            self.last_supp_db = supp_db

            eff_threshold = self.threshold_db - (self.HYSTERESIS_DB if self.open else 0.0)
            is_target_frame = (rms > 0) and (db >= eff_threshold)

            if is_target_frame:
                self.open = True
                self.hold_left = self._hold_samples
            else:
                drain = n
                self.hold_left = max(0, self.hold_left - drain)
                if not self.hold_left:
                    self.open = False

            target = 1.0 if self.open else 0.0
            if self.purity == 'ultra' and (self.open or self.gain > 1e-5 or target > 1e-5):
                part = self._postfilter(part, supp_db)
            elif self.purity == 'ultra' and len(part) == 256:
                self._prev_raw = part.copy()

            if abs(self.gain - target) < 1e-6:
                if target > 0.0:
                    result[start:start + n] = part * target
                else:
                    result[start:start + n] = 0.0
                self.gain = target
                continue

            exp_curve = self._attack_exp if target > self.gain else self._release_exp
            ramp = target + (self.gain - target) * exp_curve[:n]
            if target == 0.0:
                ramp[ramp < 1e-5] = 0.0
            result[start:start + n] = part * ramp
            self.gain = float(ramp[-1])
        return result

