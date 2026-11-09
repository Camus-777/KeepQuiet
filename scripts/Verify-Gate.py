"""Native gate UI and actual sample checks, using synthetic audio only."""
from pathlib import Path
import json
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtWidgets import QApplication
from keepquiet import ui
from keepquiet.gate import AudioGate
from keepquiet.storage import write_json, read_json

root = Path(__file__).resolve().parent.parent
checks = []
def check(name, passed):
    checks.append({'check': name, 'passed': bool(passed)})
    assert passed, name


with tempfile.TemporaryDirectory(prefix='keepquiet-gate-') as temporary:
    os.environ['KEEPQUIET_DATA_DIR'] = temporary
    write_json(Path(temporary)/'settings.json', {'auto_driver': False, 'gate_threshold_db': -60})
    app = QApplication([])
    ui.configure_app(app)
    window = ui.Window()
    window.screenshot_mode = True
    window.setWindowTitle('KeepQuiet · synthetic gate verification')
    window.show()
    app.processEvents()
    window.grab().save(str(root/'docs'/'ui-gate-current.png'))
    check('no automatic threshold controls', not any('自动' in c.text() for c in window.signal.parentWidget().findChildren(ui.QCheckBox)))
    window.resize(1120, 800)
    app.processEvents()
    check('window stays fixed', window.width() == 760 and window.height() == 360)
    window.purity_combo.setCurrentIndex(window.purity_combo.findData('custom'))
    window.open_custom_dialog()
    app.processEvents()
    check('manual controls appear in custom dialog', window.custom_dialog.isVisible() and window.gate_slider.isVisible())
    check('slider fully visible', window.gate_slider.width() >= 120)
    check('numeric input inside dialog', window.gate_value.geometry().right() < window.gate_value.parentWidget().width())
    check('numeric text visible', window.gate_value.lineEdit().geometry().width() >= 80)
    window.custom_dialog.grab().save(str(root/'docs'/'ui-gate-custom.png'))

    gate = AudioGate(-60)
    class Connection:
        def send(self, event):
            if event['command'] == 'gate':
                gate.configure(**event['value'])
    window.conn = Connection()
    window.running = True
    window.signal.set_running(True)
    window._sync_metering()
    quiet = np.full(256, 10**(-70/20), np.float32)
    check('below threshold is actual digital silence', not gate.process(quiet).any())
    window.gate_slider.setValue(-80)
    check('slider changes the live audio threshold', gate.threshold_db == -80 and window.gate_value.value() == -80)
    for _ in range(5):
        passed = gate.process(quiet)
    check('lower threshold passes quiet processed audio', np.all(passed > 0))
    window.gate_value.setValue(-50)
    check('numeric value synchronizes slider and audio', gate.threshold_db == -50 and window.gate_slider.value() == -50)
    tail = gate.process(np.tile(quiet, 40))
    check('higher threshold closes after tail and fade', not tail[-256:].any())
    window._save_gate_threshold()
    window.gate_save_timer.stop()
    check('manual preference persisted', read_json(Path(temporary)/'settings.json')['gate_threshold_db'] == -50)

    durations = []
    warm = AudioGate(-60)
    for _ in range(1200):
        start = time.perf_counter()
        warm.process(quiet)
        durations.append((time.perf_counter()-start)*1000)
    result = {'input': 'synthetic samples only; no microphone capture or driver actions',
              'checks': checks, 'hop_samples': 256, 'sample_rate': 16000,
              'gate_process_p95_ms': float(np.percentile(durations, 95)),
              'no_extra_buffering': True}
    (root/'docs'/'gate-validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    window.running = False
    window.conn = None
    window.close()
    app.processEvents()
