"""Native Qt frame/visibility diagnostic using synthetic levels, not microphone audio."""
from pathlib import Path
import argparse
import json
import math
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from keepquiet import ui

parser = argparse.ArgumentParser()
parser.add_argument('--quiet', action='store_true', help='Exercise weak filtered output across -60 dBFS')
args = parser.parse_args()
quiet_values = []
quiet_db = []

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
ui.configure_app(app)
paints, durations, checks = [], [], []
phase = ["visible"]
errors = []


class TrackedSignal(ui.SignalPath):
    def paintEvent(self, event):
        start = time.perf_counter()
        super().paintEvent(event)
        if self.running and phase[0] == "visible":
            paints.append(start)
            durations.append((time.perf_counter()-start)*1000)
            if args.quiet and time.perf_counter()-test_start > .3:
                quiet_values.append(self.envelope.values[1])


ui.SignalPath = TrackedSignal
window = ui.Window()
window.screenshot_mode = True
# This legacy diagnostic tests weak level rendering, independently of the gate.
if args.quiet:
    window.signal.envelope.set_floors((-90, -90))
window.setWindowTitle("KeepQuiet · synthetic meter diagnostic")
test_start = time.perf_counter()
window.show()
window.running = True
window.signal.set_running(True)
window._sync_metering()
start = time.perf_counter()
source = QTimer()
source.setInterval(33)
def sample():
    t = time.perf_counter()-start
    if args.quiet:
        db = -68 + 12*math.sin(t*math.tau*2)
        quiet_db.append(db)
        window.signal.set_levels(.01, 10**(db/20))
    else:
        level = .0001 + .35 * (.5+.5*math.sin(t*math.tau*2))**4
        window.signal.set_levels(level, level*.35)
source.timeout.connect(sample)
source.start()


def check(name, predicate):
    success = bool(predicate())
    checks.append({"check": name, "passed": success})
    if not success:
        errors.append(name)


def leave_dashboard():
    phase[0] = "background"
    window.page(1)
    check("other page stops animation", lambda: not window.signal.frame_timer.isActive())
    check("other page reduces IPC polling", lambda: window.timer.interval() == 100)


def dashboard():
    window.page(0)
    check("dashboard resumes animation", lambda: window.signal.frame_timer.isActive())
    check("dashboard uses fast IPC polling", lambda: window.timer.interval() == 16)


def hide_window():
    window.hide()
    check("tray hide stops animation", lambda: not window.signal.frame_timer.isActive())


def restore():
    window.showNormal()
    check("restore resumes animation", lambda: window.signal.frame_timer.isActive())


def muted():
    window.signal.set_muted(True)
    check("mute clears output immediately", lambda: window.signal.envelope.values[1] == 0.)


def finish():
    source.stop()
    window.running = False
    window.signal.set_running(False)
    window._sync_metering()
    check("stop disables animation timer", lambda: not window.signal.frame_timer.isActive())
    intervals = np.diff(paints)*1000
    result = {"input": "synthetic test envelope, no microphone capture", "painted_frames": len(paints),
              "interval_p50_ms": float(np.percentile(intervals, 50)) if len(intervals) else None,
              "interval_p95_ms": float(np.percentile(intervals, 95)) if len(intervals) else None,
              "interval_p99_ms": float(np.percentile(intervals, 99)) if len(intervals) else None,
              "paint_p95_ms": float(np.percentile(durations, 95)) if durations else None,
              "visibility_checks": checks}
    if args.quiet:
        check('continuous weak output never displayed as silence', lambda: bool(quiet_values) and min(quiet_values) > 0)
        check('weak output remains animated', lambda: max(quiet_values)-min(quiet_values) > .1)
        result.update(output_db_range=[min(quiet_db), max(quiet_db)],
                      displayed_range=[min(quiet_values), max(quiet_values)],
                      old_floor_hidden_fraction=float(np.mean(np.array(quiet_db) <= -60)))
    path = Path(__file__).resolve().parent.parent/'docs'/('meter-quiet-validation.json' if args.quiet else 'meter-validation.json')
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    window.close()
    app.quit()


QTimer.singleShot(2200, leave_dashboard)
if args.quiet:
    QTimer.singleShot(1200, lambda: window.grab().save(str(Path(__file__).resolve().parent.parent/'docs'/'ui-quiet-meter.png')))
QTimer.singleShot(2400, dashboard)
QTimer.singleShot(2600, hide_window)
QTimer.singleShot(2800, restore)
QTimer.singleShot(3000, window.showMinimized)
QTimer.singleShot(3200, lambda: check("minimize stops animation", lambda: not window.signal.frame_timer.isActive()))
QTimer.singleShot(3400, restore)
QTimer.singleShot(3600, muted)
QTimer.singleShot(3900, finish)
app.exec()
assert not errors, errors
assert len(paints) > 60, "Animation did not repaint between telemetry samples"
