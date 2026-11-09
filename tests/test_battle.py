from types import SimpleNamespace
from contextlib import nullcontext
import time

import numpy as np
import pytest

from keepquiet.audio import Bridge
from keepquiet.battle import BattleEffect, CEILING, DRIVE
from keepquiet.devices import Route
from test_profiles import make_window, close_window


def test_distortion_adds_harmonics_with_ten_percent_less_drive():
    x = (.05 * np.sin(2 * np.pi * 500 * np.arange(16000) / 16000)).astype(np.float32)
    y = BattleEffect(16000).process(x)
    assert np.isfinite(y).all() and np.max(np.abs(y)) <= CEILING
    assert np.isclose(DRIVE, (10 ** (36 / 20)) * .9)
    previous = np.clip(x * (10 ** (36 / 20)), -.98, .98)
    assert np.sqrt(np.mean(y ** 2)) <= np.sqrt(np.mean(previous ** 2))
    spectrum = np.abs(np.fft.rfft(y)) ** 2
    assert (spectrum.sum() - spectrum[500]) / spectrum.sum() > .1
    assert not BattleEffect(16000).process(np.zeros(256, np.float32)).any()


def test_battle_audio_ignores_normal_parameters_and_restores_normal_path(monkeypatch):
    monkeypatch.setattr('keepquiet.audio.processor', lambda *a, **k: SimpleNamespace(
        push=lambda x: SimpleNamespace(audio=x.copy())))
    route = Route(0, 1, rate=16000, block_ms=16)
    signal = (.05 * np.sin(2 * np.pi * 500 * np.arange(256) / 16000)).astype(np.float32)

    def make(floor, gain, battle):
        b = Bridge(route, {}, object(), gate_config={'threshold_db': floor, 'purity': 'ultra'},
                   output_gain_db=gain, battle_mode=battle)
        b.input = b.output = SimpleNamespace(active=True)
        b._started = time.perf_counter()
        b.captured_output = []
        b.ring.push = lambda y: b.captured_output.append(y.copy())
        return b

    def tick(b):
        b.capture.put((signal.copy(), time.perf_counter()))
        b.tick()
        return b.captured_output[-1]

    a, b = make(-20, 18, True), make(-90, -12, True)
    normal_state = a.gate.status().copy()
    gain_state = (a.output_gain.gain, a.output_gain.limiter, a.output_gain.gain_db)
    for _ in range(8):
        np.testing.assert_array_equal(tick(a), tick(b))
    assert a.gate.status() == normal_state
    assert (a.output_gain.gain, a.output_gain.limiter, a.output_gain.gain_db) == gain_state
    # Ordinary controls can change without altering the active battle effect.
    a.configure_gate({'threshold_db': -90, 'purity': 'balanced'})
    a.configure_output_gain(-12)
    np.testing.assert_array_equal(tick(a), tick(b))
    restored = make(a.gate.threshold_db, a.output_gain.gain_db, False)
    restored.configure_gate({'purity': a.gate.purity})
    reference = make(-90, -12, False)
    reference.configure_gate({'threshold_db': -90, 'purity': 'balanced'})
    np.testing.assert_array_equal(tick(restored), tick(reference))


def test_ui_battle_is_session_only_and_preserves_profile(tmp_path, monkeypatch):
    app, w = make_window(tmp_path, monkeypatch)
    w.gain_value.setValue(6)
    w.gate_value.setValue(-66)
    w.gate_save_timer.stop()
    w.gain_save_timer.stop()
    w._persist_profile()
    profile = w.settings.copy()
    sent = []
    w.running = True
    w.conn = SimpleNamespace(send=sent.append)
    restarts = []
    w._request_run_restart = lambda: restarts.append(w.battle_enabled)
    w.battle_button.click()
    assert w.battle_enabled and w.battle_button.isChecked()
    assert not w.purity_combo.isEnabled() and w.purity_combo.battle_locked
    w.purity_combo.showPopup()
    assert not w.purity_combo.view().isVisible()
    assert restarts[-1] is True and not sent
    assert w.settings == profile
    w.battle_button.click()
    assert not w.battle_enabled and w.settings == profile
    assert w.purity_combo.isEnabled() and not w.purity_combo.battle_locked
    assert restarts[-1] is False and not sent
    w.battle_button.click()
    close_window(app, w)
    app, restored = make_window(tmp_path, monkeypatch)
    assert not restored.battle_enabled and not restored.battle_button.isChecked()
    assert (restored.gate_threshold_db, restored.output_gain_db) == (-66, 6)
    close_window(app, restored)


def test_worker_rejects_live_battle_switch_without_remeasurement(monkeypatch):
    from keepquiet import worker
    events, changes = [], []
    commands = [{'command': 'battle_mode', 'value': False}, {'command': 'stop'}]
    conn = SimpleNamespace(send=events.append, poll=lambda: bool(commands) and any(e['kind'] == 'running' for e in events),
                           recv=lambda: commands.pop(0), close=lambda: None)
    class FakeBridge:
        def __init__(self, *a, **kw):
            changes.append(kw['battle_mode'])
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def set_metering(self, value): pass
        def set_battle_mode(self, value): changes.append(value)
    monkeypatch.setattr(worker, 'Bridge', FakeBridge)
    def forbidden(*a, **kw):
        raise AssertionError('Raw battle must not load denoising models or voiceprints')
    monkeypatch.setattr(worker, 'load_models', forbidden)
    monkeypatch.setattr(worker, 'load_voiceprint', forbidden)
    monkeypatch.setattr(worker, 'read_json', lambda *a: {})
    measurements = []
    def benchmark(a, b, models, voice, **kwargs):
        assert models is None and voice is None and kwargs['battle_mode']
        measurements.append(True)
        return Route(a, b), {}
    monkeypatch.setattr(worker, 'run_benchmark', benchmark)
    monkeypatch.setattr(worker, 'audio_priority', lambda: nullcontext({}))
    worker.worker_entry('run', {'input_id': 0, 'output_id': 1, 'battle_mode': True}, conn)
    assert changes == [True]
    assert measurements == [True]
    assert any(e['kind'] == 'running' for e in events)
    assert any(e['kind'] == 'error' for e in events)


@pytest.mark.parametrize('rate', [16000, 48000])
def test_battle_keeps_raw_sample_rate_and_never_resamples(monkeypatch, rate):
    def forbidden(*args, **kwargs):
        raise AssertionError('No denoiser should be constructed')
    monkeypatch.setattr('keepquiet.audio.processor', forbidden)
    b = Bridge(Route(0, 1, rate=rate, block_ms=16), None, None, battle_mode=True)
    assert b.resampler is None
    b.input = b.output = SimpleNamespace(active=True)
    b._started = time.perf_counter()
    output = []
    b.ring.push = lambda y: output.append(y.copy())
    x = np.linspace(-.02, .02, b.route.frames, dtype=np.float32)
    b.capture.put((x, time.perf_counter()))
    b.tick()
    assert len(output[0]) == len(x)


def test_raw_and_normal_routes_use_independent_caches(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from keepquiet import benchmark
    from keepquiet.storage import write_json
    from keepquiet.storage import read_json
    monkeypatch.setenv('KEEPQUIET_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(benchmark, 'fingerprint', lambda *a: 'test-device')
    for battle, rate in ((True, 16000), (False, 48000)):
        write_json(benchmark.cache_path(0, 1, battle_mode=battle), {
            'schema': 2, 'created_at': datetime.now(timezone.utc).isoformat(),
            'selected': {'route': Route(0, 1, rate=rate).to_dict()}})
    assert read_json(benchmark.cache_path(0, 1))['selected']['route']['rate'] == 48000
    assert read_json(benchmark.cache_path(0, 1, battle_mode=True))['selected']['route']['rate'] == 16000


def test_raw_battle_never_constructs_or_calls_denoiser_then_resumes_it(monkeypatch):
    calls = []
    def factory(*args, **kwargs):
        calls.append('construct')
        def push(x):
            calls.append('infer')
            return SimpleNamespace(audio=x.copy())
        return SimpleNamespace(push=push)
    monkeypatch.setattr('keepquiet.audio.processor', factory)
    b = Bridge(Route(0, 1, rate=16000, block_ms=16), {}, object(), battle_mode=True)
    b.input = b.output = SimpleNamespace(active=True)
    b._started = time.perf_counter()
    x = np.linspace(-.03, .03, 256, dtype=np.float32)
    for _ in range(3):
        b.capture.put((x, time.perf_counter()))
        b.tick()
    assert not calls
    restored = Bridge(Route(0, 1, rate=16000), {}, object())
    restored.input = restored.output = SimpleNamespace(active=True)
    restored._started = time.perf_counter()
    restored.capture.put((x, time.perf_counter()))
    restored.tick()
    assert calls == ['construct', 'infer']


def test_battle_still_obeys_mute_and_benchmark_silence(monkeypatch):
    monkeypatch.setattr('keepquiet.audio.processor', lambda *a, **k: SimpleNamespace())
    for probe, muted in ((True, False), (False, True)):
        b = Bridge(Route(0, 1, rate=16000, block_ms=16), None, None,
                   battle_mode=True, probe=probe)
        b.muted = muted
        b.ring.push(np.full(512, .98, np.float32))
        out = np.empty((256, 2), np.float32)
        b._out_callback(out, 256, None, None)
        assert not out.any()
