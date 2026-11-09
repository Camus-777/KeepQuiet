"""Preset selection and deliberate slider dragging affect the real UI state."""
from types import SimpleNamespace

from keepquiet.storage import read_json, write_json


def make_window(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('KEEPQUIET_DATA_DIR', str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from keepquiet import ui

    monkeypatch.setattr(ui, 'devices', lambda **kwargs: [])
    app = QApplication.instance() or QApplication([])
    ui.configure_app(app)
    window = ui.Window()
    window.screenshot_mode = True
    window.show()
    app.processEvents()
    return app, window


def close_window(app, window):
    window.gate_save_timer.stop()
    window.gain_save_timer.stop()
    window.tray.hide()
    window._exiting = True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_legacy_settings_preserve_effective_threshold_and_manual_gain(tmp_path, monkeypatch):
    write_json(tmp_path/'settings.json', {
        'purity_mode': 'ultra', 'gate_threshold_db': -60, 'output_gain_db': 6})
    app, window = make_window(tmp_path, monkeypatch)
    assert window.purity_mode == 'custom'
    assert window.filter_mode == 'ultra'
    assert window.gate_value.value() == -56
    assert window.gain_value.value() == 6
    saved = read_json(tmp_path/'settings.json')
    assert saved['profile_schema'] == 1 and saved['gate_threshold_db'] == -56
    close_window(app, window)


def test_presets_sync_controls_and_manual_changes_restore_custom(tmp_path, monkeypatch):
    app, window = make_window(tmp_path, monkeypatch)
    sent = []
    window.conn = SimpleNamespace(send=sent.append)
    window.running = True
    restarts = []
    window._request_run_restart = lambda: restarts.append((window.filter_mode, window.gate_threshold_db))
    for mode, floor in (('natural', -63), ('balanced', -60), ('ultra', -56)):
        window.purity_combo.setCurrentIndex(window.purity_combo.findData(mode))
        assert window.gate_slider.value() == window.gate_value.value() == floor
        assert window.gain_slider.value() == window.gain_value.value() == 0
        assert window.filter_mode == mode
    assert restarts == [('natural', -63), ('balanced', -60), ('ultra', -56)]
    assert not sent
    window.gain_value.setValue(6)
    assert window.purity_mode == window.purity_combo.currentData() == 'custom'
    assert window.filter_mode == 'ultra'
    assert (window.gate_value.value(), window.gain_value.value()) == (-56, 6)
    window.gate_value.setValue(-70)
    window.purity_combo.setCurrentIndex(window.purity_combo.findData('balanced'))
    assert (window.gate_value.value(), window.gain_value.value()) == (-60, 0)
    window.purity_combo.setCurrentIndex(window.purity_combo.findData('custom'))
    assert (window.gate_value.value(), window.gain_value.value()) == (-70, 6)
    assert window.filter_mode == 'ultra'
    close_window(app, window)
    from keepquiet import ui
    restored = ui.Window()
    assert restored.purity_mode == 'custom'
    assert (restored.gate_value.value(), restored.gain_value.value()) == (-70, 6)
    close_window(app, restored)


def test_sliders_ignore_track_clicks_but_accept_handle_drag(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt, QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider

    app, window = make_window(tmp_path, monkeypatch)
    for slider in (window.gate_slider, window.gain_slider):
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        handle = slider.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider)

        def send(kind, point, buttons):
            app.sendEvent(slider, QMouseEvent(
                kind, QPointF(point), QPointF(slider.mapToGlobal(point)),
                Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))

        start_value = slider.value()
        track = QPoint(slider.width() - 15, handle.center().y())
        send(QEvent.Type.MouseButtonPress, track, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseButtonRelease, track, Qt.MouseButton.NoButton)
        assert slider.value() == start_value
        start = handle.center()
        end = start + QPoint(40, 0)
        send(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseMove, end, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)
        assert slider.value() != start_value
        assert window.purity_mode == 'custom'
    close_window(app, window)


def test_custom_filter_requests_remeasurement_and_restores_after_preset(tmp_path, monkeypatch):
    app, window = make_window(tmp_path, monkeypatch)
    sent = []
    window.conn = SimpleNamespace(send=sent.append)
    window.running = True
    restarts = []
    window._request_run_restart = lambda: restarts.append(window.filter_mode)
    combo = window.purity_combo
    combo.setCurrentIndex(combo.findData('custom'))
    window.custom_dialog.filter_combo.setCurrentIndex(1)
    assert window.filter_mode == window.custom_filter_mode == 'ultra'
    assert restarts[-1] == 'ultra' and not sent
    assert read_json(tmp_path/'settings.json')['custom_filter_mode'] == 'ultra'
    combo.setCurrentIndex(combo.findData('balanced'))
    combo.setCurrentIndex(combo.findData('custom'))
    assert window.custom_dialog.filter_combo.currentText() == '强效'
    assert window.filter_mode == 'ultra'
    close_window(app, window)
