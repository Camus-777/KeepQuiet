"""Native Windows UI review with temporary settings; never opens audio streams."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QComboBox, QCheckBox, QToolTip, QStyle, QStyleOptionSlider
from PySide6.QtCore import Qt, QEvent, QPoint, QPointF
from PySide6.QtGui import QCursor, QEnterEvent, QHelpEvent, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from keepquiet import ui

checks = []
def check(name, passed):
    checks.append({'check': name, 'passed': bool(passed)})
    assert passed, name

with tempfile.TemporaryDirectory(prefix='keepquiet-pixel-review-') as temporary:
    os.environ['KEEPQUIET_DATA_DIR'] = temporary
    app = QApplication([])
    ui.configure_app(app)
    window = ui.Window()
    window.screenshot_mode = True
    window.show()
    app.processEvents()
    window._reset_metrics()
    for i, name in enumerate(('dashboard', 'devices')):
        window.page(i)
        app.processEvents()
        check(f'{name} page visible', window.stack.currentIndex() == i)
        window.grab().save(str(root/f'docs/pixel-{name}.png'))
    window.page(0)
    check('dashboard fits default window without scrolling',
          not window.stack.widget(0).verticalScrollBar().isVisible())
    check('fixed window and only CPU metric', window.size().width() == 760 and
          window.size().height() == 360 and set(window.metrics) == {'cpu'})
    check('custom controls stay in their dialog', not window.custom_dialog.isVisible() and
          not window.custom_button.isVisible())
    check('main button says start running', window.start.text() == '开始运行')
    controls = (window.findChildren(QPushButton) + window.findChildren(QComboBox) +
                window.findChildren(QCheckBox) + [window.metrics['cpu']])
    check('only question marks have hover explanations',
          all(not control.toolTip() for control in controls) and not window.tray.toolTip())
    window.resize(700, 420)
    app.processEvents()
    window.grab().save(str(root/'docs/pixel-compact.png'))
    check('window ignores resize requests', window.size().width() == 760 and window.size().height() == 360)
    check('signal labels do not overlap mode selection',
          window.signal.mapTo(window, window.signal.rect().bottomLeft()).y() <
          window.purity_combo.mapTo(window, window.purity_combo.rect().topLeft()).y())
    check('compact layout keeps main action visible', window.start.isVisible() and
          window.rect().contains(window.start.mapTo(window, window.start.rect().bottomRight())))
    window.page(1)
    app.processEvents()
    check('compact device page fits width',
          window.stack.widget(1).widget().width() <= window.stack.widget(1).viewport().width())
    check('manual benchmark remains available', window.bench_button.isVisible())
    window.grab().save(str(root/'docs/pixel-devices-compact.png'))
    window.page(0)
    window.resize(760, 440)
    combo = window.purity_combo
    combo.setCurrentIndex(combo.findData('custom'))
    combo.activated.emit(combo.currentIndex())
    app.processEvents()
    dialog = window.custom_dialog
    check('selecting custom opens the adjustment dialog', dialog.isVisible() and window.custom_button.isVisible())
    check('custom filter has ordinary and strong modes',
          [dialog.filter_combo.itemText(i) for i in range(dialog.filter_combo.count())] == ['普通', '强效'])
    dialog.grab().save(str(root/'docs/pixel-custom-settings.png'))
    dot = dialog.gate_help
    global_point = dot.mapToGlobal(QPoint(10, 10))
    app.sendEvent(dot, QEnterEvent(QPointF(10, 10), QPointF(10, 10), QPointF(global_point)))
    check('parameter help waits one second without a question cursor',
          dot.timer.isActive() and dot.timer.interval() == 1000 and
          dot.cursor().shape() == Qt.CursorShape.ArrowCursor and dot.width() == 16 and
          not dot.popup.isVisible())
    QTest.qWait(1100)
    check('parameter help appears after one second', dot.popup.isVisible() and
          dot.popup.text() == dot.explanation)
    dot.popup.grab().save(str(root/'docs/pixel-custom-help.png'))
    app.sendEvent(dot, QEvent(QEvent.Type.Leave))
    app.processEvents()
    check('parameter help disappears on leave', not dot.popup.isVisible())
    for control in (window.gate_value, window.gain_value):
        check(f'{control.accessibleName()} remains readable', control.lineEdit().width() >= 80)
    check('sliders retain audio limits', window.gate_slider.minimum() == -90 and window.gain_slider.maximum() == 18)
    for slider in (window.gate_slider, window.gain_slider):
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        handle = slider.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider)
        track = QPoint(slider.width() - 15, handle.center().y())
        before = slider.value()
        for event_type, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                    (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
            app.sendEvent(slider, QMouseEvent(
                event_type, QPointF(track), QPointF(slider.mapToGlobal(track)),
                Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
        check(f'{slider.accessibleName()} ignores a track click', slider.value() == before)
    dialog.hide()
    def wheel(control):
        point = control.rect().center()
        app.sendEvent(control, QWheelEvent(
            QPointF(point), QPointF(control.mapToGlobal(point)), QPoint(0, 0), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate, False))

    for control in (window.purity_combo, window.input_combo, window.output_combo):
        before = control.currentIndex()
        wheel(control)
        check(f'{control.accessibleName()} ignores mouse wheel', control.currentIndex() == before)

    window.page(1)
    app.processEvents()
    device = window.input_combo
    device.clear()
    for name in ('Headset Microphone / WASAPI', 'USB Microphone / WASAPI'):
        device.addItem(name)
    device_positions = []
    for index in range(device.count()):
        device.setCurrentIndex(index)
        device.showPopup()
        app.processEvents()
        device_positions.append((device.view().window().x(), device.view().window().y()))
        device.hidePopup()
    check('device menu stays anchored when selection changes', len(set(device_positions)) == 1)
    device.showPopup()
    app.processEvents()
    device_view = device.view()
    target = device_view.visualRect(device_view.model().index(1, 0)).center()
    app.sendEvent(device_view.viewport(), QHelpEvent(
        QEvent.Type.ToolTip, target, device_view.viewport().mapToGlobal(target)))
    check('device option does not show hover text', not QToolTip.isVisible() and
          not device.itemData(1, Qt.ItemDataRole.ToolTipRole))
    app.sendEvent(device_view.viewport(), QMouseEvent(
        QEvent.Type.MouseMove, QPointF(target), QPointF(device_view.viewport().mapToGlobal(target)),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    app.processEvents()
    device_popup_image = device_view.window().grab()
    device_popup_image.save(str(root/'docs/pixel-device-hover.png'))
    check('hovered device option is highlighted',
          device_popup_image.toImage().pixelColor(device_view.mapTo(device_view.window(), target)).name().lower() == ui.BLUE.lower())
    device.hidePopup()
    def edge_color(control):
        return control.grab().toImage().pixelColor(0, control.height() // 2).name().lower()

    def hover(control):
        center = control.rect().center()
        global_center = control.mapToGlobal(center)
        QCursor.setPos(global_center)
        app.sendEvent(control, QEnterEvent(QPointF(center), QPointF(center), QPointF(global_center)))
        QTest.qWait(100)

    def select_popup_row(combo, row):
        view = combo.view()
        choice = view.visualRect(view.model().index(row, 0)).center()
        gpos = view.viewport().mapToGlobal(choice)
        # Native popup selection needs the cursor over the target row. This
        # review requires an interactive desktop; failed clicks must fail it.
        QCursor.setPos(gpos)
        QTest.mouseMove(view.viewport(), choice)
        QTest.qWait(100)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=choice)
        app.processEvents()

    device.setCurrentIndex(0)
    window.raise_()
    window.activateWindow()
    hover(device)
    check('hovered device selector has a blue border', edge_color(device) == '#2868ff')
    QTest.mouseClick(device, Qt.MouseButton.LeftButton)
    app.processEvents()
    check('clicked device selector has a blue border',
          device.view().isVisible() and edge_color(device) == '#2868ff')
    select_popup_row(device, 1)
    check('clicking a device option selects the target device', device.currentIndex() == 1)
    check('device menu closes automatically after selection', not device.view().isVisible())
    check('device selector border returns to idle after selection',
          not device.view().isVisible() and edge_color(device) == '#aaaaaa')
    window.page(0)
    app.processEvents()

    QTest.mouseClick(window.theme_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    check('white theme uses moon and white canvas', window.theme == 'light' and
          window.theme_button.accessibleName() == '切换到黑色界面' and
          window.grab().toImage().pixelColor(4, 4).name().lower() == '#ffffff')
    window.grab().save(str(root/'docs/pixel-light.png'))
    window.page(1)
    app.processEvents()
    window.grab().save(str(root/'docs/pixel-devices-light.png'))
    window.page(0)
    window.custom_dialog.show()
    app.processEvents()
    window.custom_dialog.grab().save(str(root/'docs/pixel-custom-light.png'))
    window.custom_dialog.hide()
    QTest.mouseClick(window.theme_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    check('dark theme uses sun and black canvas', window.theme == 'dark' and
          window.theme_button.accessibleName() == '切换到白色界面' and
          window.grab().toImage().pixelColor(4, 4).name().lower() == '#000000')
    check('clicked buttons keep their normal border', edge_color(window.theme_button) == '#ffffff')

    popup_positions = []
    for index in range(combo.count()):
        combo.setCurrentIndex(index)
        app.processEvents()
        combo.showPopup()
        app.processEvents()
        popup = combo.view().window()
        popup_positions.append((popup.x(), popup.y()))
        check(f'{combo.itemText(index)} menu has no hover explanation',
              not combo.itemData(index, Qt.ItemDataRole.ToolTipRole))
        combo.hidePopup()
    check('purity menu stays anchored when selection changes', len(set(popup_positions)) == 1)
    combo.showPopup()
    app.processEvents()
    view = combo.view()
    hovered = view.model().index(2, 0)
    point = view.visualRect(hovered).center()
    app.sendEvent(view.viewport(), QMouseEvent(
        QEvent.Type.MouseMove, QPointF(point), QPointF(view.viewport().mapToGlobal(point)),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    app.processEvents()
    popup_image = view.window().grab()
    popup_image.save(str(root/'docs/pixel-purity-hover.png'))
    check('hovered purity option is highlighted',
          popup_image.toImage().pixelColor(view.mapTo(view.window(), point)).name().lower() == ui.BLUE.lower())
    app.sendEvent(view.viewport(), QHelpEvent(
        QEvent.Type.ToolTip, point, view.viewport().mapToGlobal(point)))
    check('hovered purity option shows no explanation', not QToolTip.isVisible())
    combo.hidePopup()
    hover(combo)
    check('hovered purity selector has a blue border', edge_color(combo) == '#2868ff')
    QTest.mouseClick(combo, Qt.MouseButton.LeftButton)
    app.processEvents()
    check('clicked purity selector has a blue border',
          combo.view().isVisible() and edge_color(combo) == '#2868ff')
    select_popup_row(combo, 1)
    check('clicking a purity option selects the target mode', combo.currentIndex() == 1)
    check('purity menu closes automatically after selection', not combo.view().isVisible())
    check('purity selector border returns to idle after selection',
          not combo.view().isVisible() and edge_color(combo) == '#aaaaaa')
    combo.setCurrentIndex(1)
    window.gate_value.setValue(-65)
    window.gain_value.setValue(6)
    check('gain and floor controls synchronize', window.gate_slider.value() == -65 and window.gain_slider.value() == 6)
    check('manual adjustment selects custom', combo.currentData() == 'custom')
    window.gate_value.setValue(-60)
    window.gain_value.setValue(0)
    # Stop the pending writes: review uses temporary settings regardless.
    window.gate_save_timer.stop()
    window.gain_save_timer.stop()
    window.record_voice()
    app.processEvents()
    dialog = window.enrollment_dialog
    check('opening reading guide does not capture audio', window.proc is None and not dialog.recording)
    check('enrollment opens with focus on start', dialog.start.hasFocus())
    check('enrollment passage present', any(label.text() == ui.EnrollmentDialog.PASSAGE
          for label in dialog.findChildren(QLabel)))
    dialog.grab().save(str(root/'docs/pixel-enrollment.png'))
    dialog.reject()
    app.processEvents()
    window.page(0)
    window.start.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    check('keyboard focus visible on primary action', window.start.hasFocus())
    window.grab().save(str(root/'docs/pixel-keyboard-focus.png'))
    # Preview a received envelope, with no synthetic worker or microphone session.
    window.signal.running = True
    window.signal.envelope.values = [0.6, 0.35]
    window.signal.update()
    app.processEvents()
    window.grab().save(str(root/'docs/pixel-meter-preview.png'))
    window.signal.running = False
    window.signal.envelope.reset()
    check('battle mode is above the ready message',
          window.battle_button.mapTo(window, window.battle_button.rect().bottomLeft()).y() <
          window.message.mapTo(window, window.message.rect().topLeft()).y())
    def battle_background():
        point = window.battle_button.mapTo(window, QPoint(3, window.battle_button.height() // 2))
        return window.grab().toImage().pixelColor(point).name().lower()
    check('battle mode starts with the dark canvas background',
          not window.battle_enabled and battle_background() == '#000000')
    profile = (window.purity_mode, window.gate_threshold_db, window.output_gain_db, window.filter_mode)
    QTest.mouseClick(window.battle_button, Qt.MouseButton.LeftButton)
    check('battle mode has a red active background', window.battle_enabled and battle_background() == '#d12d3c')
    check('battle mode locks the purity selector', not window.purity_combo.isEnabled() and
          window.purity_combo.battle_locked and window.purity_combo.accessibleName() == '战斗模式')
    QTest.mouseClick(window.purity_combo, Qt.MouseButton.LeftButton)
    check('locked purity selector cannot open', not window.purity_combo.view().isVisible())
    window.grab().save(str(root/'docs/pixel-battle-dark.png'))
    window.theme_button.click()
    app.processEvents()
    check('battle mode remains red in the light theme', battle_background() == '#d12d3c')
    window.grab().save(str(root/'docs/pixel-battle-light.png'))
    window.battle_button.click()
    app.processEvents()
    check('disabled battle mode matches the light canvas', battle_background() == '#ffffff')
    check('leaving battle restores the purity selector', window.purity_combo.isEnabled() and
          not window.purity_combo.battle_locked)
    check('battle switch preserves ordinary profile parameters',
          profile == (window.purity_mode, window.gate_threshold_db, window.output_gain_db, window.filter_mode))
    window.theme_button.click()
    window.proc = SimpleNamespace(is_alive=lambda: True)
    window.conn = SimpleNamespace(poll=lambda: False, send=lambda value: None)
    window.running = False
    window.set_busy(True)
    check('preparation locks mode and custom controls', not window.battle_button.isEnabled() and
          not window.purity_combo.isEnabled() and not window.custom_dialog.filter_combo.isEnabled())
    QTest.mouseClick(window.battle_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.purity_combo, Qt.MouseButton.LeftButton)
    check('preparation clicks cannot change or open modes', not window.battle_enabled and
          not window.purity_combo.view().isVisible())
    window.handle_worker_event('running', {'route': ui.Route(0, 1).to_dict(), 'muted': True})
    check('running restores mode controls with mute preserved', window.battle_button.isEnabled() and
          window.purity_combo.isEnabled() and window.muted and window.mute.text() == '恢复声音')
    window.proc = window.conn = None
    window.running = False
    window.signal.set_running(False)
    window.set_busy(False)
    window.tray.hide()
    window._exiting = True
    window.close()
    (root/'docs/pixel-ui-validation.json').write_text(json.dumps({
        'environment': 'native Windows Qt, temporary settings, no recording or driver actions',
        'checks': checks,
        'meter_preview': 'illustrative envelope values only; not audio quality evidence'
    }, indent=2), encoding='utf-8')
    print(json.dumps(checks, indent=2))
