"""Time-based display envelopes; independent of audio processing and Qt."""
import math
from .gate import clamp_floor


class MeterEnvelope:
    FLOOR_DB = -90.
    ATTACK_SECONDS = .035
    RELEASE_SECONDS = .18
    STALE_SECONDS = .25

    def __init__(self):
        self.values = [0., 0.]
        self.targets = [0., 0.]
        self.last_sample = None
        self.floors = [self.FLOOR_DB, self.FLOOR_DB]

    def set_floors(self, floors):
        self.floors[:] = [clamp_floor(value, self.FLOOR_DB) for value in floors]

    @staticmethod
    def normalize(rms, floor_db=FLOOR_DB):
        try:
            value = float(rms)
        except (TypeError, ValueError, OverflowError):
            return 0.
        if not math.isfinite(value) or value <= 0:
            return 0.
        # Filtered quiet speech can be well below -60 dBFS. That was a display
        # cutoff, not a statement that the model had returned silence.
        floor_db = clamp_floor(floor_db, MeterEnvelope.FLOOR_DB)
        return min(1., max(0., (20 * math.log10(value) - floor_db) / -floor_db))

    def feed(self, levels, now):
        self.targets[:] = [self.normalize(value, floor) for value, floor in zip(levels, self.floors)]
        self.last_sample = now

    def reset(self):
        self.values[:] = [0., 0.]
        self.targets[:] = [0., 0.]
        self.last_sample = None

    def mute_output(self):
        self.values[1] = self.targets[1] = 0.

    def advance(self, elapsed, now):
        if self.last_sample is None or now - self.last_sample > self.STALE_SECONDS:
            self.targets[:] = [0., 0.]
        dt = min(.1, max(0., elapsed))
        changed = False
        for i, target in enumerate(self.targets):
            current = self.values[i]
            tau = self.ATTACK_SECONDS if target > current else self.RELEASE_SECONDS
            value = current + (target - current) * -math.expm1(-dt / tau)
            # Keep small, valid movements visible; only settle at sub-pixel
            # precision rather than snapping quiet changes to each new sample.
            if abs(value - target) < .000001:
                value = target
            changed |= value != current
            self.values[i] = value
        return changed
