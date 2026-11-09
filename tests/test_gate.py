"""Actual sample-path behavior, without opening a microphone or changing user data."""
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest

from keepquiet.gate import AudioGate, clamp_floor


def tone(db, hops=1):
    return np.full(256*hops, 10**(db/20), np.float32)


def test_manual_threshold_changes_real_samples_and_preserves_duration():
    gate = AudioGate(threshold_db=-60)
    quiet = tone(-70, 4)
    assert not gate.process(quiet).any()
    gate.configure(threshold_db=-80)
    passed = gate.process(quiet)
    assert len(passed) == len(quiet)
    np.testing.assert_allclose(passed[-256:], quiet[-256:], atol=1e-9)
    assert not gate.process(np.empty(0, np.float32)).size
    gate.configure(threshold_db=-50)
    suppressed = gate.process(tone(-70, 40))
    assert not suppressed[-256:].any()


def test_hysteresis_and_hold_preserve_soft_tails_but_noise_eventually_closes():
    gate = AudioGate(-60)
    gate.process(tone(-50, 4))
    gate.process(tone(-63, 30))  # below opening threshold, above closing threshold
    assert gate.open
    held = gate.process(tone(-75, 4))
    assert gate.open and np.all(held > 0)
    closed = gate.process(tone(-75, 40))
    assert not gate.open and not closed[-256:].any()
    assert not gate.process(np.zeros(256, np.float32)).any()


def test_live_threshold_change_fades_without_a_step_or_lookahead():
    gate = AudioGate(-70)
    x = tone(-40, 4)
    gate.process(x)
    previous = gate.gain * x[-1]
    gate.configure(threshold_db=-20)
    y = gate.process(tone(-40, 40))
    assert len(y) == 256*40
    assert abs(float(y[0])-previous) < float(x[0])*.01
    assert np.max(np.abs(np.diff(y))) < float(x[0])*.01
    assert not y[-256:].any()


@pytest.mark.parametrize('bad', [None, 'bad', float('nan'), float('inf')])
def test_invalid_saved_threshold_uses_a_finite_default(bad):
    assert clamp_floor(bad) == -60
    assert AudioGate(bad).threshold_db == -60


def test_threshold_endpoints_are_bounded():
    assert AudioGate(-1000).threshold_db == -90
    assert AudioGate(1000).threshold_db == -20


def test_bridge_gates_model_audio_and_meters_actual_output(monkeypatch):
    from keepquiet.audio import Bridge
    from keepquiet.devices import Route
    import time

    class QuietModel:
        def push(self, pcm):
            return SimpleNamespace(audio=np.full(256, 10**(-70/20), np.float32))
    monkeypatch.setattr('keepquiet.audio.processor', lambda *a, **kw: QuietModel())
    bridge = Bridge(Route(0, 1, rate=16000, block_ms=16), None, None,
                    gate_config={'threshold_db': -60})
    bridge.input = bridge.output = SimpleNamespace(active=True)
    bridge.set_metering(True)
    def tick():
        bridge.capture.put((np.full(256, .2, np.float32), time.perf_counter()))
        bridge.tick()
    tick()
    assert not bridge.ring.data.any()
    assert bridge.take_levels()['output_level'] < 2e-6
    bridge.configure_gate({'threshold_db': -80})
    for _ in range(4):
        tick()
    assert 0 < bridge.take_levels()['output_level'] < .001
    assert bridge.ring.data.max() < .001  # never the loud raw input
    data = np.empty((256, 2), np.float32)
    bridge.set_muted(True)
    bridge._out_callback(data, 256, None, None)
    assert not data.any()


def test_worker_delivers_initial_and_live_threshold_to_audio_bridge(monkeypatch):
    from keepquiet import worker
    from keepquiet.devices import Route
    clock = [0.]
    seen = []
    route = Route(0, 1, rate=16000, block_ms=8)
    class FakeBridge:
        _started = 0.
        def __init__(self, *args, **kwargs): seen.append(kwargs['gate_config'])
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def set_metering(self, enabled): pass
        def tick(self): clock[0] += .008
        def configure_gate(self, config): seen.append(config)
        def configure_output_gain(self, value): seen.append(('gain', value))
        def gate_status(self): return {'threshold_db': -45, 'open': False, 'gain': 0.}
    class Connection:
        def __init__(self): self.events = []; self.changed = False; self.gain_changed = False
        def send(self, event): self.events.append(event)
        def poll(self): return clock[0] >= (.04 if self.changed else .016)
        def recv(self):
            if not self.changed:
                self.changed = True
                return {'command': 'gate', 'value': {'threshold_db': -45}}
            if not self.gain_changed:
                self.gain_changed = True
                return {'command': 'output_gain', 'value': 6}
            return {'command': 'stop'}
        def close(self): pass
    monkeypatch.setattr(worker, 'Bridge', FakeBridge)
    monkeypatch.setattr(worker, 'load_models', lambda **kw: object())
    monkeypatch.setattr(worker, 'load_voiceprint', lambda: object())
    monkeypatch.setattr(worker, 'run_benchmark', lambda *args, **kwargs: (route, {}))
    monkeypatch.setattr(worker, 'read_json', lambda *args: {})
    monkeypatch.setattr(worker, 'audio_priority', lambda: nullcontext({}))
    monkeypatch.setattr(worker.time, 'perf_counter', lambda: clock[0])
    connection = Connection()
    worker.worker_entry('run', {'input_id': 0, 'output_id': 1,
                               'gate': {'threshold_db': -75}}, connection)
    assert seen == [{'threshold_db': -75}, {'threshold_db': -45}, ('gain', 6)]
    assert any(e['kind'] == 'gate' for e in connection.events)
    assert not any(e['kind'] == 'error' for e in connection.events)


def test_ui_slider_numeric_live_update_and_preferences(tmp_path, monkeypatch):
    # Keep unit-test Qt windows away from the interactive desktop/IME COM
    # context. Verify-Gate.py separately exercises the native Windows plugin.
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from keepquiet import ui
    from keepquiet.storage import write_json, read_json
    monkeypatch.setenv('KEEPQUIET_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ui, 'devices', lambda: [])
    write_json(tmp_path/'settings.json', {'gate_threshold_db': -72, 'auto_driver': False})
    app = QApplication.instance() or QApplication([])
    ui.configure_app(app)
    window = ui.Window()
    window.screenshot_mode = True
    window.show()
    app.processEvents()
    assert window.gate_value.lineEdit().geometry().width() >= 80
    messages = []
    window.conn = SimpleNamespace(send=messages.append)
    window.running = True
    assert window.gate_slider.value() == window.gate_value.value() == -72
    window.gate_slider.setValue(-80)
    assert window.gate_value.value() == -80
    window.gate_value.setValue(-55)
    assert window.gate_slider.value() == -55
    assert messages[-1] == {'command': 'gate', 'value': {'threshold_db': -55}}
    window._save_gate_threshold()
    window.gate_save_timer.stop()
    saved = read_json(tmp_path/'settings.json')
    assert saved['gate_threshold_db'] == saved['custom_gate_threshold_db'] == -55
    assert saved['purity_mode'] == 'custom' and saved['filter_mode'] == 'balanced'
    assert saved['auto_driver'] is False
    window.running = False
    window.conn = None
    window.close()
    window.tray.hide()
    window.deleteLater()
    app.processEvents()
    restored = ui.Window()
    restored.screenshot_mode = True
    assert restored.gate_value.value() == -55
    restored.close()
    restored.tray.hide()
    restored.deleteLater()
    app.processEvents()
