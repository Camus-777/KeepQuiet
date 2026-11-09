"""Real native Qt event-loop check, with synthetic worker and temporary settings."""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from keepquiet import ui

root = Path(__file__).resolve().parent.parent
checks, errors, messages = [], [], []
def check(name, passed):
    checks.append({'check': name, 'passed': bool(passed)})
    if not passed: errors.append(name)

with tempfile.TemporaryDirectory(prefix='keepquiet-background-') as temporary:
    os.environ['KEEPQUIET_DATA_DIR'] = temporary
    app = QApplication([])
    ui.configure_app(app)
    window = ui.Window()
    window.screenshot_mode = True
    # Exercise the real Windows tray, while keeping the diagnostic silent.
    window.tray.showMessage = lambda *args: None
    window.show()
    check('closing the last window does not quit the event loop', not app.quitOnLastWindowClosed())
    def idle_close():
        window.close()
    def after_idle_close():
        available = ui.QSystemTrayIcon.isSystemTrayAvailable()
        check('idle close stays recoverable in background',
              not window._exiting and (not window.isVisible() if available else window.isMinimized()))
        window._tray_activated(ui.QSystemTrayIcon.ActivationReason.Trigger)
        check('tray activation restores the window', window.isVisible() and not window.isMinimized())
        window.conn = SimpleNamespace(send=messages.append, poll=lambda: False)
        window.proc = SimpleNamespace(is_alive=lambda: True)
        window.operation = 'run'
        window.running = True
        window.signal.set_running(True)
        window._sync_metering()
        window.close()
    def after_audio_close():
        check('closing active UI does not stop the worker',
              not any(m.get('command') == 'stop' for m in messages) and window.proc.is_alive())
        check('background pauses meter rendering', not window.signal.frame_timer.isActive())
        window.restore_window()
        check('restore resumes meter rendering', window.signal.frame_timer.isActive())
        window.running = False
        window.proc = window.conn = None
        window.operation = None
        window.exit_app()
        check('explicit exit closes the window', window._exiting and not window.isVisible())
    QTimer.singleShot(50, idle_close)
    QTimer.singleShot(150, after_idle_close)
    QTimer.singleShot(300, after_audio_close)
    QTimer.singleShot(1500, app.quit)
    app.exec()
    check('all lifecycle steps ran after closing the last window', len(checks) == 7)
    result = {'input': 'native Qt event loop; synthetic worker; no microphone capture or driver actions',
              'checks': checks}
    (root/'docs'/'background-validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    assert not errors, errors
