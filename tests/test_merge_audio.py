"""Checks for the merged live audio path without opening real devices."""
from types import SimpleNamespace

import numpy as np

from keepquiet.audio import AudioRing, Bridge
from keepquiet.devices import Route
from keepquiet.gate import AudioGate


def test_8ms_callbacks_keep_a_32ms_waterline():
    ring = AudioRing(16000, 128)
    assert ring.target == 512
    ring.push(np.full(512, .2, np.float32))
    out = np.empty(128, np.float32)
    for step in range(200):
        if step % 2:
            ring.push(np.full(256, .2, np.float32))
        ring.pull_into(out)
        assert np.min(out) > .19
    assert ring.underflows == 0


def test_gate_uses_displayed_threshold_without_hidden_mode_offsets():
    signal = np.full(512, 10 ** (-57 / 20), np.float32)
    natural = AudioGate(-60, purity='natural')
    balanced = AudioGate(-60, purity='balanced')
    ultra = AudioGate(-60, purity='ultra')
    assert natural.process(signal).any()
    assert balanced.process(signal).any()
    assert ultra.process(signal).any()
    assert all(g.threshold_db == -60 for g in (natural, balanced, ultra))
    assert not AudioGate(-56, purity='ultra').process(signal).any()


def test_ultra_retains_target_when_raw_microphone_is_louder():
    rate = 16000
    target = (.01 * np.sin(2 * np.pi * 220 * np.arange(rate) / rate)).astype(np.float32)
    gate = AudioGate(-60, purity='ultra')
    output = np.concatenate([
        gate.process(target[i:i + 256], in_rms=.1)
        for i in range(0, len(target), 256)
    ])
    input_rms = np.sqrt(np.mean(target[rate // 2:] ** 2))
    output_rms = np.sqrt(np.mean(output[rate // 2:] ** 2))
    assert gate.open
    assert output_rms >= input_rms * .5


def test_mute_and_benchmark_never_forward_audio(monkeypatch):
    monkeypatch.setattr('keepquiet.audio.processor', lambda *a, **k: SimpleNamespace())
    route = Route(0, 1, rate=16000, block_ms=16)
    for probe, mute in ((True, False), (False, True)):
        bridge = Bridge(route, None, None, probe=probe)
        bridge.ring.push(np.full(512, .5, np.float32))
        if mute:
            bridge.set_muted(True)
        out = np.full((256, 2), 1, np.float32)
        bridge._out_callback(out, 256, None, None)
        assert not out.any()


def test_monitor_avoids_virtual_output_and_reports_actual_state(monkeypatch):
    monkeypatch.setattr('keepquiet.audio.processor', lambda *a, **k: SimpleNamespace())
    import sounddevice as sd

    devices = [
        {'name': 'Microphone', 'max_output_channels': 0},
        {'name': 'CABLE Input', 'max_output_channels': 2},
        {'name': 'Headphones', 'max_output_channels': 2},
    ]
    streams = []

    class Stream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            streams.append(self)
        def start(self): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(sd, 'query_devices', lambda index=None: devices if index is None else devices[index])
    monkeypatch.setattr(sd, 'default', SimpleNamespace(device=(0, 1)))
    monkeypatch.setattr(sd, 'OutputStream', Stream)
    bridge = Bridge(Route(0, 1, rate=16000, block_ms=16), None, None)
    assert bridge.set_monitor(True)
    assert streams[0].kwargs['device'] == 2
    bridge.monitor_ring.push(np.full(512, .3, np.float32))
    out = np.empty((256, 2), np.float32)
    streams[0].kwargs['callback'](out, 256, None, None)
    np.testing.assert_allclose(out, .3)
    assert not bridge.set_monitor(False)
