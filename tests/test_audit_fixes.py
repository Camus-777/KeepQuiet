from types import SimpleNamespace

import pytest


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('KEEPQUIET_DATA_DIR', str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from keepquiet import ui
    monkeypatch.setattr(ui, 'devices', lambda **kwargs: [])
    app = QApplication.instance() or QApplication([])
    w = ui.Window()
    w.screenshot_mode = True
    yield w
    w.proc = w.conn = None
    w._exiting = True
    w.tray.hide()
    w.close()
    w.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('content', [b'{', b'[1]', b'42', b'\xff'])
def test_invalid_settings_preserved_and_window_recovers(tmp_path, monkeypatch, content):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('KEEPQUIET_DATA_DIR', str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from keepquiet import ui
    monkeypatch.setattr(ui, 'devices', lambda **kwargs: [])
    (tmp_path / 'settings.json').write_bytes(content)
    app = QApplication.instance() or QApplication([])
    w = ui.Window()
    w.screenshot_mode = True
    try:
        assert w.settings_recovered
        assert '恢复默认' in w.message.text()
        backups = list(tmp_path.glob('settings.json.invalid-*'))
        assert len(backups) == 1 and backups[0].read_bytes() == content
        assert w.purity_mode == 'balanced'
    finally:
        w._exiting = True
        w.tray.hide()
        w.close()
        w.deleteLater()
        app.processEvents()


def test_json_bom_is_accepted(tmp_path):
    from keepquiet.storage import read_json
    p = tmp_path / 'settings.json'
    p.write_text('{"theme":"light"}', encoding='utf-8-sig')
    assert read_json(p) == {'theme': 'light'}
    assert not list(tmp_path.glob('*.invalid-*'))


def test_startup_locks_parameters_until_running(window):
    from keepquiet.devices import Route
    sent = []
    window.proc = object()
    window.conn = SimpleNamespace(send=sent.append)
    window.operation = 'run'
    window.set_busy(True)
    assert not window.purity_combo.isEnabled()
    assert not window.battle_button.isEnabled()
    assert not window.gain_value.isEnabled()
    assert not sent
    window.handle_worker_event('running', {'route': Route(0, 1).to_dict()})
    assert window.purity_combo.isEnabled() and window.battle_button.isEnabled()
    assert window.gain_value.isEnabled()
    assert not any(m['command'] in ('gate', 'output_gain', 'battle_mode') for m in sent)


@pytest.mark.parametrize('online_succeeds', [True, False])
def test_driver_check_distinguishes_network_failure(window, tmp_path, monkeypatch, online_succeeds):
    from keepquiet import driver
    monkeypatch.setattr(driver, 'installed_driver', lambda: {'DriverVersion': '3.5.2.0'})
    def latest():
        if not online_succeeds:
            raise TimeoutError('offline')
        return driver.BUNDLED_NAME
    monkeypatch.setattr(driver, 'official_latest', latest)
    monkeypatch.setattr(driver, 'stage_package', lambda name: (tmp_path / 'fake.zip', 'fake', '3.5.2.0'))
    monkeypatch.setattr(driver, 'verify_package', lambda *a: {'state': 'verified'})
    result = driver.check_update()
    assert result['online_checked'] is online_succeeds
    window.settings['last_driver_check'] = 123
    window.refresh_devices = lambda: None
    window.handle_worker_event('driver', result)
    if online_succeeds:
        assert window.settings['last_driver_check'] > 123
        assert '无需更新' in window.driver_status.text()
    else:
        assert window.settings['last_driver_check'] == 123
        assert '无法确认' in window.driver_status.text()


def test_monitor_failure_reports_reason_without_failing_main_output(window, monkeypatch):
    import sounddevice as sd
    from keepquiet.audio import Bridge
    from keepquiet.devices import Route
    monkeypatch.setattr('keepquiet.audio.processor', lambda *a, **k: SimpleNamespace())
    dev = {'name': 'Headphones', 'max_output_channels': 2}
    monkeypatch.setattr(sd, 'query_devices', lambda i=None: [dev] if i is None else dev)
    monkeypatch.setattr(sd, 'default', SimpleNamespace(device=(-1, 0)))
    def fail(**kwargs):
        raise RuntimeError('output device busy')
    monkeypatch.setattr(sd, 'OutputStream', fail)
    bridge = Bridge(Route(0, 1, rate=16000), None, None)
    assert not bridge.set_monitor(True)
    assert bridge.monitor_error == 'output device busy'
    assert bridge.fault is None
    window.running = True
    window.handle_worker_event('monitor', {'enabled': False, 'error': bridge.monitor_error})
    assert window.running
    assert 'output device busy' in window.message.text()
    bridge.set_monitor(False)
    assert bridge.monitor_error is None
