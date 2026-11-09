"""The CPU meter reports the whole-app share used by Task Manager."""
from types import SimpleNamespace


def test_cpu_meter_uses_total_machine_share(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('KEEPQUIET_DATA_DIR', str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from keepquiet import ui

    monkeypatch.setattr(ui, 'devices', lambda **kwargs: [])
    app = QApplication.instance() or QApplication([])
    ui.configure_app(app)
    window = ui.Window()
    window.screenshot_mode = True
    window.running = True
    window.cpu_count = 8
    window.cpu_process = SimpleNamespace(cpu_percent=lambda _: 80.0)
    window.cpu_ui_process = SimpleNamespace(cpu_percent=lambda _: 8.0)
    window.handle_worker_event('stats', {
        'estimated_local_ms': 100.0,
        'dsp_p95_ms': 1.0,
        'host_xruns': 0,
        'input_drops': 0,
        'output_underruns': 0,
        'output_drops': 0,
    })
    assert window.metrics['cpu'].text() == '11.0%'
    assert not window.metrics['cpu'].toolTip()
    window.tray.hide()
    window._exiting = True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_theme_and_fixed_window_restore(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('KEEPQUIET_DATA_DIR', str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from keepquiet import ui
    from keepquiet.storage import read_json

    monkeypatch.setattr(ui, 'devices', lambda **kwargs: [])
    app = QApplication.instance() or QApplication([])
    ui.configure_app(app)
    window = ui.Window()
    window.screenshot_mode = True
    assert window.stack.count() == 2
    assert window.minimumSize() == window.maximumSize()
    assert set(window.metrics) == {'cpu'}
    window.theme_button.click()
    assert window.theme == 'light'
    assert window.theme_button.accessibleName() == '切换到黑色界面'
    assert read_json(tmp_path/'settings.json')['theme'] == 'light'
    window.tray.hide()
    window._exiting = True
    window.close()
    window.deleteLater()
    app.processEvents()

    restored = ui.Window()
    restored.screenshot_mode = True
    assert restored.theme == 'light'
    assert restored.theme_button.accessibleName() == '切换到黑色界面'
    restored.tray.hide()
    restored._exiting = True
    restored.close()
    restored.deleteLater()
    app.processEvents()
