"""Render and exercise the reading guide without recording a microphone."""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtWidgets import QApplication
from keepquiet import ui

root = Path(__file__).resolve().parent.parent
checks = []
def check(name, success):
    checks.append({'check': name, 'passed': bool(success)})
    assert success, name

with tempfile.TemporaryDirectory(prefix='keepquiet-guide-') as temporary:
    os.environ['KEEPQUIET_DATA_DIR'] = temporary
    app = QApplication([])
    ui.configure_app(app)
    window = ui.Window()
    window.screenshot_mode = True
    window.show()
    window.record_voice()
    app.processEvents()
    dialog = window.enrollment_dialog
    dialog.grab().save(str(root/'docs/ui-enrollment-0.1.7.png'))
    check('opening the passage does not record', window.proc is None and not dialog.recording)
    check('reading passage shown', any(ui.EnrollmentDialog.PASSAGE == c.text() for c in dialog.findChildren(ui.QLabel)))
    messages = []
    def launch(mode):
        window.operation = mode
        window.proc = SimpleNamespace(is_alive=lambda: False, exitcode=0, join=lambda **kw: None)
        window.conn = SimpleNamespace(poll=lambda: False, close=lambda: None, send=messages.append)
    window.launch = launch
    dialog.begin()
    check('start enters the enrollment workflow', dialog.recording and not dialog.start.isEnabled())
    window.handle_worker_event('progress', {'message': '请持续说话，还剩 5.0 秒', 'fraction': .16})
    check('progress visible with passage', '5.0' in dialog.status.text() and dialog.isVisible())
    window.handle_worker_event('finished', {})
    window.poll()
    check('successful completion closes guide', window.enrollment_dialog is None and not dialog.isVisible())
    window.record_voice()
    dialog = window.enrollment_dialog
    dialog.begin()
    dialog.reject()
    check('cancel sends stop to the enrollment worker', {'command': 'stop'} in messages)
    window.proc = window.conn = None
    window.running = False
    window.operation = None
    window.exit_app()
    (root/'docs/enrollment-validation-20261107.json').write_text(json.dumps(
        {'input': 'native Qt with synthetic worker; no microphone capture', 'checks': checks}, indent=2), encoding='utf-8')
    print(json.dumps(checks, indent=2))
