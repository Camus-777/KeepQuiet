"""Closing the surface must never terminate the audio session."""
from types import SimpleNamespace


def test_background_lifecycle_and_explicit_exit(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('KEEPQUIET_DATA_DIR', str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from keepquiet import ui
    monkeypatch.setattr(ui, 'devices', lambda: [])
    app = QApplication.instance() or QApplication([])
    ui.configure_app(app)
    assert not app.quitOnLastWindowClosed()

    window = ui.Window()
    window.screenshot_mode = True
    calls = []
    tray = SimpleNamespace(show=lambda: calls.append('tray-show'),
                           hide=lambda: calls.append('tray-hide'),
                           showMessage=lambda *args: calls.append('hint'))
    window.tray.hide()
    window.tray = tray
    monkeypatch.setattr(ui.QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    connection = SimpleNamespace(send=lambda message: calls.append(message), poll=lambda: False)
    class Process:
        alive = True
        def is_alive(self): return self.alive
        def join(self, **kwargs): self.alive = False; calls.append('joined')
        def terminate(self): calls.append('terminated'); self.alive = False
    process = Process()
    for operation, running in ((None, False), ('run', True), ('run', False),
                               ('benchmark', False), ('driver_install', False)):
        window.operation = operation
        window.running = running
        window.proc = process if operation else None
        window.conn = connection if operation else None
        window.restore_window()
        app.processEvents()
        window.close()
        assert not window.isVisible() and not window._exiting
        assert process.is_alive()
        assert not any(isinstance(c, dict) and c.get('command') == 'stop' for c in calls)
        window._tray_activated(ui.QSystemTrayIcon.ActivationReason.DoubleClick)
        assert window.isVisible() and not window.isMinimized()
    assert calls.count('hint') == 1

    monkeypatch.setattr(ui.QSystemTrayIcon, 'isSystemTrayAvailable', lambda: False)
    window.operation = 'run'
    window.running = True
    window.close()
    assert window.isMinimized() and window.isVisible() and not window._exiting
    assert process.is_alive()
    window.restore_window()
    assert not window.isMinimized()

    window.operation = 'driver_install'
    window.exit_app()
    assert not window._exiting and process.is_alive()
    window.operation = 'run'
    window.exit_app()
    assert window._exiting and not window.isVisible()
    assert {'command': 'stop'} in calls and 'joined' in calls and 'tray-hide' in calls
    assert 'terminated' not in calls
    window.proc = window.conn = None
    window.running = False
    window.deleteLater()
    app.processEvents()
