"""Render actual empty/cached UI states without recording or driver deployment."""
from pathlib import Path
import json
import os
import sys

# Use the Windows platform plugin so system Chinese fonts match the shipped UI.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtWidgets import QApplication
from keepquiet.ui import Window, configure_app
from keepquiet.storage import read_json, data_dir

app = QApplication([])
configure_app(app)
window = Window()
window.screenshot_mode = True
window.show()
app.processEvents()
out = Path(__file__).resolve().parent.parent / "docs"
window.grab().save(str(out/"ui-workbench.png"))
reports = sorted((data_dir()/"benchmarks").glob("*.json"))
if reports:
    window.show_benchmark(read_json(reports[-1]))
window.page(1)
window.nav[1].setFocus()
app.processEvents()
window.grab().save(str(out/"ui-driver.png"))
status = read_json(data_dir()/"driver-update.json")
if status and status.get("installed"):
    window.driver_status.setText(f"VB-CABLE {status['installed']['DriverVersion']} 已检测到。")
window.page(0)
window.nav[0].setFocus()
app.processEvents()
window.grab().save(str(out/"ui-fixed.png"))
window.handle_worker_event("error", "测试错误：请检查输入设备。")
window.handle_worker_event("finished", {})
assert window.message.text() == "测试错误：请检查输入设备。"
assert window.start.minimumHeight() >= 38
assert window.input_combo.height() >= 38
assert window.mute.isEnabled() is False
assert window.controls.isVisible()
assert window.start.isVisible()
assert window.start.mapTo(window, window.start.rect().bottomRight()).y() < window.height()
assert window.output_combo.mapTo(window.input_combo.parentWidget(), window.output_combo.rect().topLeft()).y() >= window.input_combo.y() + window.input_combo.height()
scroll = window.stack.widget(0)
assert scroll.widget().width() <= scroll.viewport().width()
window.close()
print('UI screenshots and error-state checks passed')
