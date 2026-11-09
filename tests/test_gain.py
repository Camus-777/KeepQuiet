"""Output gain changes real samples, without reopening gated noise."""
import time
from types import SimpleNamespace

import numpy as np
import pytest

from keepquiet.gain import OutputGain, CEILING, clamp_gain


def test_unity_gain_is_transparent_and_silence_stays_silent():
    x = np.linspace(-.5, .5, 4096, dtype=np.float32)
    gain = OutputGain()
    np.testing.assert_array_equal(gain.process(x), x)
    assert not gain.process(np.empty(0, np.float32)).size
    assert not OutputGain(18).process(np.zeros(1000, np.float32)).any()


def test_gain_ramps_live_changes_and_reaches_requested_amplitude():
    gain = OutputGain()
    x = np.full(16000, .02, np.float32)
    gain.configure(6)
    y = gain.process(x)
    assert len(y) == len(x)
    assert 0 < y[0]-.02 < .0001
    assert np.max(np.abs(np.diff(y))) < .0001
    np.testing.assert_allclose(y[-256:], .02*10**(.3), rtol=1e-5)
    gain.configure(0)
    z = gain.process(x)
    assert abs(float(z[0]-y[-1])) < .0001
    np.testing.assert_allclose(z[-256:], .02, rtol=1e-5)


@pytest.mark.parametrize('rate', [16000, 44100, 48000])
def test_limiter_bounds_peaks_and_recovers_without_added_samples(rate):
    gain = OutputGain(18, rate=rate)
    x = np.tile(np.array([1., -.9, .1, -.05], np.float32), rate//4)
    y = gain.process(x)
    assert len(y) == len(x) and np.isfinite(y).all()
    assert np.max(np.abs(y)) <= CEILING+1e-6
    quiet = gain.process(np.full(rate, .01, np.float32))
    assert np.max(np.abs(np.diff(quiet))) < .001
    np.testing.assert_allclose(quiet[-256:], .01*10**(.9), rtol=1e-5)


@pytest.mark.parametrize('value, expected', [(None, 0), ('bad', 0),
                         (float('nan'), 0), (float('inf'), 0), (-10, 0), (100, 18)])
def test_gain_settings_are_finite_and_bounded(value, expected):
    assert clamp_gain(value) == expected


def test_bridge_gain_follows_gate_and_meter_reports_limited_output(monkeypatch):
    from keepquiet.audio import Bridge
    from keepquiet.devices import Route
    level = [.0001]
    class Model:
        def push(self, x):
            return SimpleNamespace(audio=np.full(256, level[0], np.float32))
    monkeypatch.setattr('keepquiet.audio.processor', lambda *a, **kw: Model())
    bridge = Bridge(Route(0, 1, rate=16000, block_ms=16), None, None,
                    output_gain_db=18, gate_config={'threshold_db': -60})
    bridge.input = bridge.output = SimpleNamespace(active=True)
    bridge.set_metering(True)
    def tick():
        bridge.capture.put((np.full(256, .8, np.float32), time.perf_counter()))
        bridge.tick()
    tick()
    assert not bridge.ring.data.any()  # gain must not reopen below-threshold audio
    bridge.take_levels()
    level[0] = .02
    for _ in range(10): tick()
    assert .14 < bridge.output_level < .17
    assert bridge.take_levels()['output_level'] > .1
    bridge.configure_output_gain(0)
    for _ in range(40): tick()
    np.testing.assert_allclose(bridge.output_level, .02, rtol=1e-4)
    bridge.configure_output_gain(18)
    level[0] = .7
    for _ in range(40): tick()
    assert bridge.ring.data.max() <= CEILING+1e-6
    assert bridge.take_levels()['output_level'] <= CEILING+1e-6


def test_ui_gain_live_update_save_and_restore(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('KEEPQUIET_DATA_DIR', str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from keepquiet import ui
    from keepquiet.storage import read_json, write_json
    monkeypatch.setattr(ui, 'devices', lambda: [])
    write_json(tmp_path/'settings.json', {'auto_driver': False})
    app = QApplication.instance() or QApplication([])
    ui.configure_app(app)
    window = ui.Window()
    window.screenshot_mode = True
    window.show()
    app.processEvents()
    assert window.gain_value.lineEdit().width() >= 80
    assert window.gain_value.value() == 0
    messages = []
    window.conn = SimpleNamespace(send=messages.append)
    window.running = True
    window.gain_slider.setValue(6)
    assert window.gain_value.value() == 6
    window.gain_value.setValue(9)
    assert window.gain_slider.value() == 9
    assert messages[-1] == {'command': 'output_gain', 'value': 9}
    window._save_output_gain()
    window.gain_save_timer.stop()
    saved = read_json(tmp_path/'settings.json')
    assert saved['output_gain_db'] == saved['custom_output_gain_db'] == 9
    assert saved['purity_mode'] == 'custom' and saved['filter_mode'] == 'balanced'
    assert saved['auto_driver'] is False
    window.conn = None
    window.running = False
    window.tray.hide()
    window._exiting = True
    window.close()
    window.deleteLater()
    app.processEvents()
    restored = ui.Window()
    restored.screenshot_mode = True
    assert restored.gain_value.value() == 9
    restored.tray.hide()
    restored._exiting = True
    restored.close()
    restored.deleteLater()
    app.processEvents()
