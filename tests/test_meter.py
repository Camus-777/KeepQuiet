import math
from types import SimpleNamespace

import numpy as np
import pytest

from keepquiet.meter import MeterEnvelope
from keepquiet.audio import Bridge
from keepquiet.devices import Route


def test_quiet_filtered_output_remains_visible_across_old_display_cutoff():
    envelope = MeterEnvelope()
    values = []
    # A continuous quiet output crosses the former -60 dBFS floor. The input
    # stays louder, like a microphone followed by target-speaker extraction.
    for frame in range(180):
        now = frame / 60
        if frame % 2 == 0:
            output_db = -65 + 8 * math.sin(now * math.tau)
            envelope.feed((.01, 10 ** (output_db / 20)), now)
        envelope.advance(1 / 60, now)
        values.append(envelope.values[1])
    assert min(values[30:]) > .1
    assert max(values[30:]) - min(values[30:]) > .08
    assert MeterEnvelope.normalize(10 ** (-80 / 20)) > .1
    assert MeterEnvelope.normalize(0) == 0
    assert MeterEnvelope.normalize(10 ** (-100 / 20)) == 0


def test_small_quiet_level_changes_are_interpolated_between_samples():
    envelope = MeterEnvelope()
    envelope.feed((.001, .001), 0.)
    envelope.values[:] = envelope.targets
    before = envelope.values[1]
    envelope.feed((.001, .001 * 10 ** (.02 / 20)), .016)
    target = envelope.targets[1]
    envelope.advance(.016, .016)
    assert before < envelope.values[1] < target
    first = envelope.values[1]
    envelope.advance(.016, .032)
    assert first < envelope.values[1] < target


def test_attack_uses_multiple_frames_instead_of_jumping_to_sample():
    envelope = MeterEnvelope()
    envelope.feed((1., .1), 0.)
    values = []
    for step in range(1, 11):
        envelope.advance(.016, step*.016)
        values.append(envelope.values[0])
    assert 0 < values[0] < .5
    assert all(a < b for a, b in zip(values, values[1:]))
    assert .98 < values[-1] < 1


def test_envelope_speed_is_independent_of_render_frame_rate():
    def run(fps):
        envelope = MeterEnvelope()
        envelope.feed((.1, .01), 0.)
        for step in range(1, int(.2*fps)+1):
            envelope.advance(1/fps, step/fps)
        return envelope.values
    assert run(30) == pytest.approx(run(60), abs=1e-7)


def test_stale_telemetry_decays_and_silence_does_not_animate():
    envelope = MeterEnvelope()
    envelope.feed((1., 1.), 0.)
    envelope.advance(.1, .1)
    first = envelope.values[0]
    envelope.advance(.016, .3)
    assert envelope.values[0] < first
    for step in range(200):
        envelope.advance(.016, .316+step*.016)
    assert envelope.values == [0., 0.]
    assert not envelope.advance(.016, 5.)


def test_invalid_audio_levels_are_silent_and_mute_is_immediate():
    envelope = MeterEnvelope()
    envelope.feed((float("nan"), float("inf")), 0.)
    assert envelope.targets == [0., 0.]
    envelope.feed((.1, .1), 0.)
    envelope.advance(.05, .05)
    envelope.mute_output()
    assert envelope.values[0] > 0 and envelope.values[1] == envelope.targets[1] == 0
    envelope.reset()
    assert envelope.values == envelope.targets == [0., 0.]


def test_meter_rms_covers_whole_window_and_ignores_empty_model_hops(monkeypatch):
    class BufferedModel:
        def __init__(self):
            self.pending = []
        def push(self, pcm):
            self.pending.append(pcm)
            return SimpleNamespace(audio=np.concatenate(self.pending) if len(self.pending) == 2
                                   else np.empty(0, np.float32))
    monkeypatch.setattr("keepquiet.audio.processor", lambda *a, **kw: BufferedModel())
    bridge = Bridge(Route(0, 1, rate=16000, block_ms=8), None, None)
    bridge.input = bridge.output = SimpleNamespace(active=True)
    bridge.set_metering(True)
    import time
    for amplitude in (.1, .3):
        bridge.capture.put((np.full(128, amplitude, np.float32), time.perf_counter()))
        bridge.tick()
    expected = math.sqrt((.1**2+.3**2)/2)
    levels = bridge.take_levels()
    assert levels["input_level"] == pytest.approx(expected)
    # Output telemetry must follow the actual gated samples, including the
    # short opening ramp, rather than the pre-gate model output.
    actual = bridge.ring.data[:bridge.ring.size]
    assert levels["output_level"] == pytest.approx(float(np.sqrt(np.mean(actual*actual))), rel=1e-5)
    assert 0 < levels["output_level"] <= expected
    assert bridge.take_levels() == {"input_level": 0., "output_level": 0.}
    bridge.set_muted(True)
    assert bridge.take_levels()["output_level"] == 0.


@pytest.mark.parametrize("metering", [False, True])
def test_worker_fast_levels_are_separate_from_slow_stats(monkeypatch, metering):
    from contextlib import nullcontext
    from keepquiet import worker
    clock = [0.]
    route = Route(0, 1, rate=16000, block_ms=8)
    class FakeBridge:
        _started = 0.
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def set_metering(self, value): self.metering = value
        def tick(self): clock[0] += .008
        def take_levels(self): return {"input_level": .1, "output_level": .01}
        def gate_status(self): return {"threshold_db": -60, "open": True, "gain": 1.}
        def stats(self):
            return dict.fromkeys(("host_xruns", "input_drops", "output_underruns", "output_drops"), 0)
    class FakeConnection:
        def __init__(self): self.events = []
        def send(self, event): self.events.append(event)
        def poll(self): return clock[0] >= 1.2
        def recv(self): return {"command": "stop"}
        def close(self): pass
    monkeypatch.setattr(worker, "Bridge", FakeBridge)
    monkeypatch.setattr(worker, "load_models", lambda **kw: object())
    monkeypatch.setattr(worker, "load_voiceprint", lambda: object())
    monkeypatch.setattr(worker, "run_benchmark", lambda *args, **kwargs: (route, {}))
    monkeypatch.setattr(worker, "read_json", lambda *args: {})
    monkeypatch.setattr(worker, "audio_priority", lambda: nullcontext({}))
    monkeypatch.setattr(worker.time, "perf_counter", lambda: clock[0])
    connection = FakeConnection()
    worker.worker_entry("run", {"input_id": 0, "output_id": 1, "metering": metering}, connection)
    events = connection.events
    assert not any(e["kind"] == "error" for e in events)
    assert sum(e["kind"] == "stats" for e in events) == 2
    count = sum(e["kind"] == "levels" for e in events)
    assert 20 <= count <= 36 if metering else count == 0
