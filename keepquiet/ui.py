"""Native Qt control surface; all audio/model/driver work is out of process."""
from __future__ import annotations
import multiprocessing as mp
from pathlib import Path
import sys
import time

from PySide6.QtCore import Qt, QTimer, QRectF, QPoint, QPointF, QUrl, QLockFile, QSize, QEvent, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QComboBox, QFrame, QStackedWidget, QProgressBar,
    QCheckBox, QFileDialog,
    QSystemTrayIcon, QMenu, QMessageBox, QScrollArea, QSlider, QSpinBox, QAbstractSpinBox, QDialog,
    QStyledItemDelegate, QStyle, QStyleOptionSlider,
)

from .devices import devices, Route, selection_key, find_selection
from .storage import data_dir, read_settings, write_json, forget_voiceprint
from .worker import worker_entry
from .meter import MeterEnvelope
from .gate import clamp_floor, MIN_FLOOR_DB, MAX_FLOOR_DB
from .gain import clamp_gain, MIN_GAIN_DB, MAX_GAIN_DB

from .pixel_theme import INK, BLUE, app_icon, pixel_icon, draw_glyph, style_for_theme

PURITY_PRESETS = {
    "natural": (-63, 0),
    "balanced": (-60, 0),
    "ultra": (-56, 0),
}


def configure_app(app, theme='dark'):
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    light = theme == 'light'
    background = '#FFFFFF' if light else '#000000'
    foreground = '#111111' if light else INK
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, background),
                        (QPalette.ColorRole.WindowText, foreground),
                        (QPalette.ColorRole.Base, background),
                        (QPalette.ColorRole.AlternateBase, '#F2F2F2' if light else '#202020'),
                        (QPalette.ColorRole.Text, foreground),
                        (QPalette.ColorRole.Button, background),
                        (QPalette.ColorRole.ButtonText, foreground),
                        (QPalette.ColorRole.Highlight, BLUE),
                        (QPalette.ColorRole.HighlightedText, "#FFFFFF"),
                        (QPalette.ColorRole.Link, "#2868FF")):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#888888"))
    app.setPalette(palette)
    app.setStyleSheet(style_for_theme(theme))


def label(text, name=None, wrap=False):
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    item.setWordWrap(wrap)
    return item


def button(text, callback, primary=False):
    item = QPushButton(text)
    # Mouse clicks do not keep a focus border; Tab navigation remains visible.
    item.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if primary:
        item.setObjectName("primary")
    glyph = {"开始运行": "play", "静音": "mute", "停止": "stop", "开始测试": "play",
             "录入声线 / 6 秒": "record", "导入": "import", "删除": "trash", "刷新": "refresh",
             "检查更新": "refresh", "安装 / 更新": "import", "校验模型": "filter"}.get(text)
    if glyph:
        item.setProperty('glyph_name', glyph)
        item.setIcon(pixel_icon(glyph, white=True))
        item.setIconSize(QSize(18, 18))
    item.clicked.connect(callback)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    item.setMinimumHeight(38)
    return item


def panel(title):
    widget = QFrame()
    widget.setObjectName("panel")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(20, 14, 20, 14)
    layout.setSpacing(8)
    layout.addWidget(label(title, "panelTitle"))
    return widget, layout


class AnchoredCombo(QComboBox):
    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def wheelEvent(self, event):
        self.clearFocus()
        event.ignore()

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        below = self.mapToGlobal(QPoint(0, self.height()))
        screen = QApplication.screenAt(below) or self.screen()
        bounds = screen.availableGeometry()
        x = max(bounds.left(), min(below.x(), bounds.right() - popup.width() + 1))
        y = below.y() if below.y() + popup.height() <= bounds.bottom() + 1 else below.y() - self.height() - popup.height()
        popup.move(x, max(bounds.top(), y))

    def hidePopup(self):
        super().hidePopup()
        self.clearFocus()


class DragOnlySlider(QSlider):
    def mousePressEvent(self, event):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self)
        if not handle.contains(event.position().toPoint()):
            event.accept()
            return
        super().mousePressEvent(event)


class PurityItemDelegate(QStyledItemDelegate):
    def __init__(self, combo):
        super().__init__(combo)
        self.combo = combo

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(32, size.height()))
        return size

    def paint(self, painter, option, index):
        painter.save()
        hovered = index.row() == self.combo.hovered_row
        painter.fillRect(option.rect, QColor(BLUE if hovered else ("#FFFFFF" if self.combo.light else "#000000")))
        painter.setFont(option.font)
        painter.setPen(QColor("#FFFFFF" if hovered else ("#111111" if self.combo.light else INK)))
        painter.drawText(option.rect.adjusted(12, 0, -8, 0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, index.data())
        painter.restore()


class PurityCombo(AnchoredCombo):
    def __init__(self):
        super().__init__()
        self.light = False
        self.hovered_row = -1
        self.battle_locked = False
        self.setItemDelegate(PurityItemDelegate(self))
        self.view().viewport().setMouseTracking(True)
        self.view().viewport().installEventFilter(self)

    def set_battle_locked(self, locked):
        self.hidePopup()
        self.battle_locked = bool(locked)
        self.setEnabled(not locked)
        self.setAccessibleName("战斗模式" if locked else "纯净度模式")
        self.update()

    def paintEvent(self, event):
        if not self.battle_locked:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#D12D3C'))
        painter.setPen(QColor('#FFFFFF'))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '战斗模式')

    def eventFilter(self, watched, event):
        if watched is self.view().viewport():
            if event.type() == QEvent.Type.MouseMove:
                row = self.view().indexAt(event.position().toPoint()).row()
            elif event.type() == QEvent.Type.Leave:
                row = -1
            else:
                return super().eventFilter(watched, event)
            if row != self.hovered_row:
                self.hovered_row = row
                self.view().viewport().update()
        return super().eventFilter(watched, event)

    def showPopup(self):
        if self.battle_locked:
            return
        self.hovered_row = -1
        super().showPopup()


class DeviceCombo(PurityCombo):
    def __init__(self):
        super().__init__()
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(18)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(QPen(QColor(("#111111" if self.light else "#FFFFFF") if self.isEnabled() else "#888888"), 1.4,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        x, y = self.width()-16, self.height()/2
        p.drawLine(QPointF(x-3, y-1.5), QPointF(x, y+1.5))
        p.drawLine(QPointF(x, y+1.5), QPointF(x+3, y-1.5))


class HelpDot(QLabel):
    def __init__(self, explanation):
        super().__init__("?")
        self.explanation = explanation
        self.setObjectName("helpDot")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._show_help)
        self.hovered = False
        self.popup = QLabel(explanation, self, Qt.WindowType.ToolTip)
        self.popup.setObjectName("helpPopup")
        self.popup.setWordWrap(True)
        self.popup.setFixedWidth(270)
        self.popup.adjustSize()

    def enterEvent(self, event):
        self.hovered = True
        self.timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.timer.stop()
        self.popup.hide()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.hovered = False
        self.timer.stop()
        self.popup.hide()
        super().hideEvent(event)

    def _show_help(self):
        if self.hovered:
            point = self.mapToGlobal(QPoint(self.width(), self.height()))
            bounds = self.screen().availableGeometry()
            self.popup.move(max(bounds.left(), min(point.x(), bounds.right() - self.popup.width())),
                            max(bounds.top(), min(point.y(), bounds.bottom() - self.popup.height())))
            self.popup.show()


class CustomSettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("自定义调整")
        self.setFixedWidth(460)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        layout.addWidget(label("自定义调整", "dialogTitle"))
        layout.addWidget(label("调整后立即生效，关闭窗口会保留设置。", "muted"))

        self.gate_slider = DragOnlySlider(Qt.Orientation.Horizontal)
        self.gate_slider.setRange(int(MIN_FLOOR_DB), int(MAX_FLOOR_DB))
        self.gate_slider.setValue(window.gate_threshold_db)
        self.gate_slider.setAccessibleName("音频检测下限")
        self.gate_value = QSpinBox()
        self.gate_value.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.gate_value.setRange(int(MIN_FLOOR_DB), int(MAX_FLOOR_DB))
        self.gate_value.setSuffix(" dBFS")
        self.gate_value.setValue(window.gate_threshold_db)
        self.gate_value.setFixedWidth(116)
        self.gate_value.setMinimumHeight(36)
        self.gate_value.setAccessibleName("音频检测下限数值")
        self.gate_slider.valueChanged.connect(self.gate_value.setValue)
        self.gate_value.valueChanged.connect(window._change_gate_threshold)
        self.gate_help = self._add_control(
            layout, "检测下限", "声音达到这个响度才会传出。数值越低，轻声越容易保留，但也更容易带入杂音。",
            self.gate_slider, self.gate_value)

        self.gain_slider = DragOnlySlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(MIN_GAIN_DB, MAX_GAIN_DB)
        self.gain_slider.setValue(window.output_gain_db)
        self.gain_slider.setAccessibleName("输出增益")
        self.gain_value = QSpinBox()
        self.gain_value.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.gain_value.setRange(MIN_GAIN_DB, MAX_GAIN_DB)
        self.gain_value.setSuffix(" dB")
        self.gain_value.setValue(window.output_gain_db)
        self.gain_value.setFixedWidth(116)
        self.gain_value.setMinimumHeight(36)
        self.gain_value.setAccessibleName("输出增益数值")
        self.gain_slider.valueChanged.connect(self.gain_value.setValue)
        self.gain_value.valueChanged.connect(window._change_output_gain)
        self.gain_help = self._add_control(
            layout, "输出增益", "放大处理后的声音，也会放大残余杂音；它不会让模型更容易认出你的声音。",
            self.gain_slider, self.gain_value)

        heading = QHBoxLayout()
        heading.setSpacing(6)
        heading.addWidget(label("滤波方式", "muted"))
        self.filter_help = HelpDot("普通：保留自然声线。强效：进一步压低残余杂音，但可能削弱轻声。")
        heading.addWidget(self.filter_help)
        heading.addStretch()
        layout.addLayout(heading)
        self.filter_combo = AnchoredCombo()
        self.filter_combo.addItem("普通", "balanced")
        self.filter_combo.addItem("强效", "ultra")
        self.filter_combo.setAccessibleName("自定义滤波方式")
        self.filter_combo.setCurrentIndex(self.filter_combo.findData(
            "ultra" if window.filter_mode == "ultra" else "balanced"))
        self.filter_combo.currentIndexChanged.connect(window._change_custom_filter)
        layout.addWidget(self.filter_combo)
        close = button("完成", self.close)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        window.gate_slider, window.gate_value = self.gate_slider, self.gate_value
        window.gain_slider, window.gain_value = self.gain_slider, self.gain_value

    def _add_control(self, layout, title, explanation, slider, value):
        heading = QHBoxLayout()
        heading.setSpacing(6)
        heading.addWidget(label(title, "muted"))
        help_dot = HelpDot(explanation)
        heading.addWidget(help_dot)
        heading.addStretch()
        layout.addLayout(heading)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(slider, 1)
        row.addWidget(value)
        layout.addLayout(row)
        return help_dot


class SignalPath(QWidget):
    """Real RMS meters with independently timed, fractional bar rendering."""
    def __init__(self):
        super().__init__()
        self.light = False
        self.setFixedHeight(78)
        self.running = False
        self.muted = False
        self.visual_active = False
        self.envelope = MeterEnvelope()
        self._last_frame = None
        self.frame_timer = QTimer(self)
        self.frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.frame_timer.setInterval(16)
        self.frame_timer.timeout.connect(self._animate)
        self.setAccessibleName("麦克风经 KeepQuiet 处理后送到虚拟声卡")

    def set_running(self, running):
        self.running = bool(running)
        if not self.running:
            self.envelope.reset()
        self._sync_timer()
        self.update()

    def set_visual_active(self, active):
        self.visual_active = bool(active)
        if not self.visual_active:
            self.envelope.reset()
        self._sync_timer()

    def set_muted(self, muted):
        self.muted = bool(muted)
        if muted:
            self.envelope.mute_output()
            self.update()

    def set_levels(self, input_level, output_level, at=None):
        if self.running and self.visual_active:
            self.envelope.feed((input_level, 0. if self.muted else output_level),
                               time.perf_counter() if at is None else at)

    def _sync_timer(self):
        if self.running and self.visual_active and self.isVisible():
            if not self.frame_timer.isActive():
                self._last_frame = time.perf_counter()
                self.frame_timer.start()
        else:
            self.frame_timer.stop()
            self._last_frame = None

    def _animate(self):
        now = time.perf_counter()
        elapsed = now - self._last_frame if self._last_frame is not None else .016
        self._last_frame = now
        if self.envelope.advance(elapsed, now):
            # Repaint just the meters; icons and captions remain static.
            for center in (.315, .685):
                self.update(QRect(round(self.width()*center)-42, 13, 84, 23))

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        self.frame_timer.stop()
        self._last_frame = None
        super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, mid = self.width(), 24
        centers = [round(w*.13), round(w*.5), round(w*.87)]
        background = "#FFFFFF" if self.light else "#000000"
        ink = "#111111" if self.light else INK
        p.setPen(QPen(QColor("#B8B8B8" if self.light else "#555555"), 1))
        p.drawLine(centers[0]+21, mid, centers[-1]-21, mid)
        for i, x in enumerate(centers):
            p.fillRect(x-21, mid-21, 42, 42, QColor(background))
            p.setPen(QPen(QColor(ink), 1))
            p.drawRect(x-21, mid-21, 41, 41)
            draw_glyph(p, ("mic", "filter", "cable")[i], x-14, mid-14, 3, ink)
            p.setPen(QColor(ink))
            p.setFont(QFont("Microsoft YaHei UI", 10))
            p.drawText(QRectF(x-90, mid+26, 180, 24), Qt.AlignmentFlag.AlignCenter,
                       ["麦克风", "声线过滤", "虚拟麦克风"][i])
        for j, level in enumerate(self.envelope.values):
            x = round((centers[j]+centers[j+1])/2)
            p.fillRect(x-42, mid-11, 84, 23, QColor(background))
            for k in range(20):
                amount = min(1., max(0., level*20-k)) if self.running else 0.
                # Stepped pixel columns represent the real smoothed RMS envelope.
                color = QColor(BLUE if amount > 0 else ("#B8B8B8" if self.light else "#3D3D3D"))
                height = 4 + round(amount*5)
                p.fillRect(x-38+k*4, mid-height, 2, height*2, color)


class EnrollmentDialog(QDialog):
    """Keep the reading passage visible while the existing worker records."""
    PASSAGE = "现在开始录入我的声音。\n请保持自然音量，说话清楚，语速平稳。"

    def __init__(self, window):
        super().__init__(window)
        self.recording = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("录入目标声线")
        self.setMinimumWidth(480)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("请独自朗读，保持安静环境和日常聊天音量。", "muted", True))
        passage = label(self.PASSAGE, "panelTitle", True)
        passage.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(passage)
        self.status = label("点击开始后倒计时 3 秒，再连续朗读 6 秒。", "status", True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("取消", self.reject))
        self.start = button("开始录入", self.begin, True)
        self.start.setDefault(True)
        row.addWidget(self.start)
        layout.addLayout(row)

    def showEvent(self, event):
        super().showEvent(event)
        self.start.setFocus(Qt.FocusReason.TabFocusReason)

    def begin(self):
        window = self.parentWidget()
        window.launch("enroll")
        if window.proc and window.operation == "enroll":
            self.recording = True
            self.start.setEnabled(False)
            self.status.setText("准备中，请等待录入倒计时…")
        else:
            self.status.setText(window.message.text())

    def finish(self, error):
        self.recording = False
        if error:
            self.status.setText(error)
            self.start.setText("重新录入")
            self.start.setEnabled(True)
        else:
            self.accept()

    def reject(self):
        if self.recording:
            self.parentWidget().stop_worker()
        super().reject()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KeepQuiet / Merged")
        self.setFixedSize(760, 360)
        self.proc = self.conn = None
        self.operation = None
        self._restart_pending = False
        self._restart_options = {}
        self._active_route = None
        self._benchmark_in_progress = False
        self.running = False
        self._exiting = False
        self._tray_hint_shown = False
        self.muted = False
        self.last_stats = {}
        self.cpu_process = None
        self.cpu_ui_process = None
        self.cpu_count = 1
        self.enrollment_dialog = None
        self.battle_enabled = False
        self.settings_recovered = False
        self.settings = read_settings(data_dir()/"settings.json",
            on_invalid=lambda: setattr(self, "settings_recovered", True)) or {}
        self.theme = self.settings.get("theme", "dark")
        if self.theme not in ("dark", "light"):
            self.theme = "dark"
        configure_app(QApplication.instance(), self.theme)
        saved_mode = self.settings.get("purity_mode", "balanced")
        saved_mode = saved_mode if saved_mode in (*PURITY_PRESETS, "custom") else "balanced"
        saved_floor = int(clamp_floor(self.settings.get("gate_threshold_db", -60)))
        saved_gain = int(clamp_gain(self.settings.get("output_gain_db", 0)))
        migrated = self.settings.get("profile_schema") != 1
        if migrated:
            legacy_filter = saved_mode if saved_mode in PURITY_PRESETS else "balanced"
            saved_floor = int(clamp_floor(saved_floor + {"natural": -3, "balanced": 0, "ultra": 4}[legacy_filter]))
            saved_mode = legacy_filter if (saved_floor, saved_gain) == PURITY_PRESETS[legacy_filter] else "custom"
            self.custom_filter_mode = legacy_filter
            self.custom_gate_threshold_db = saved_floor
            self.custom_output_gain_db = saved_gain
        else:
            self.custom_filter_mode = self.settings.get("custom_filter_mode", "balanced")
            if self.custom_filter_mode not in PURITY_PRESETS:
                self.custom_filter_mode = "balanced"
            self.custom_gate_threshold_db = int(clamp_floor(self.settings.get("custom_gate_threshold_db", saved_floor)))
            self.custom_output_gain_db = int(clamp_gain(self.settings.get("custom_output_gain_db", saved_gain)))
            if saved_mode in PURITY_PRESETS and (saved_floor, saved_gain) != PURITY_PRESETS[saved_mode]:
                saved_mode = "custom"
                self.custom_filter_mode = self.settings.get("filter_mode", "balanced")
                if self.custom_filter_mode not in PURITY_PRESETS:
                    self.custom_filter_mode = "balanced"
                self.custom_gate_threshold_db, self.custom_output_gain_db = saved_floor, saved_gain
        self.purity_mode = saved_mode
        self.filter_mode = self.custom_filter_mode if saved_mode == "custom" else saved_mode
        self.gate_threshold_db = saved_floor
        self.output_gain_db = saved_gain
        self._setting_profile = False
        self.gate_save_timer = QTimer(self)
        self.gate_save_timer.setSingleShot(True)
        self.gate_save_timer.setInterval(250)
        self.gate_save_timer.timeout.connect(self._save_gate_threshold)
        self.monitor_active = False
        self.gain_save_timer = QTimer(self)
        self.gain_save_timer.setSingleShot(True)
        self.gain_save_timer.setInterval(250)
        self.gain_save_timer.timeout.connect(self._save_output_gain)
        self.last_driver = None
        self._refreshing_devices = False
        self.last_error = None
        self.saw_finished = False
        self._metering_enabled = False
        self._build()
        self._apply_theme()
        if migrated:
            self._persist_profile()
        self._make_tray()
        self.refresh_devices()
        self._update_voice()
        if self.settings_recovered:
            self.message.setText("设置文件损坏，已保留备份并恢复默认设置。")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.first_run)
        self.update_timer.start(6*3600*1000)
        QTimer.singleShot(1000, self.first_run)

    def _build(self):
        root = QWidget()
        root.setObjectName("main")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 12, 16, 10)
        outer.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        mark = QLabel()
        mark.setPixmap(app_icon().pixmap(24, 24))
        brand_row.addWidget(mark)
        brand_row.addWidget(label("KeepQuiet", "brand"))
        top.addLayout(brand_row)
        top.addStretch()
        self.nav = []
        for i, text in enumerate(("音频控制", "设备管理")):
            nav = button(text, lambda checked=False, index=i: self.page(index))
            nav.setObjectName("navTop")
            nav.setProperty("glyph_name", ("control", "devices")[i])
            nav.setIcon(pixel_icon(("control", "devices")[i], white=True))
            nav.setIconSize(QSize(16, 16))
            nav.setCheckable(True)
            self.nav.append(nav)
            top.addWidget(nav)
        self.theme_button = button("", self.toggle_theme)
        self.theme_button.setObjectName("themeSwitch")
        self.theme_button.setFixedSize(38, 38)
        top.addWidget(self.theme_button)
        self.badge = label("■  待机", "badge")
        top.addWidget(self.badge)
        outer.addLayout(top)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self._dashboard()
        self._driver_page()
        outer.addWidget(self.controls)
        self.message = label("就绪", "message", True)
        self.message.setMinimumHeight(22)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(self.message, 1)
        status_row.addWidget(label("CPU", "muted"))
        self.metrics = {"cpu": label("0.0%", "footerMetric")}
        self.metrics["cpu"].setMinimumWidth(48)
        self.metrics["cpu"].setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.metrics["cpu"])
        outer.addLayout(status_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)
        self.page(0)

    def _dashboard(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(11)
        signal, ss = panel("声音通道")
        ss.setContentsMargins(16, 10, 16, 10)
        self.signal = SignalPath()
        self.signal.envelope.set_floors((self.gate_threshold_db, self.gate_threshold_db))
        ss.addWidget(self.signal)
        purity_row = QHBoxLayout()
        purity_row.setSpacing(14)
        purity_row.addWidget(label("纯净度", "muted"))
        self.purity_combo = PurityCombo()
        self.purity_combo.setAccessibleName("纯净度模式")
        self.purity_combo.addItem("自然", "natural")
        self.purity_combo.addItem("均衡", "balanced")
        self.purity_combo.addItem("强效", "ultra")
        self.purity_combo.addItem("自定义", "custom")
        self.purity_combo.setCurrentIndex(self.purity_combo.findData(self.purity_mode))
        self.purity_combo.currentIndexChanged.connect(self._change_purity)
        self.purity_combo.activated.connect(self._open_custom_on_selection)
        purity_row.addWidget(self.purity_combo, 1)
        self.custom_button = button("调整", self.open_custom_dialog)
        self.custom_button.setVisible(self.purity_mode == "custom")
        purity_row.addWidget(self.custom_button)
        ss.addLayout(purity_row)
        self.custom_dialog = CustomSettingsDialog(self)
        box.addWidget(signal)
        box.addStretch()
        self.controls = QWidget()
        self.controls.setObjectName("actionBar")
        actions = QHBoxLayout(self.controls)
        actions.setContentsMargins(0, 8, 0, 0)
        actions.setSpacing(10)
        self.battle_button = button("战斗模式", self._toggle_battle_mode)
        self.battle_button.setObjectName("battleMode")
        self.battle_button.setCheckable(True)
        self.battle_button.setMinimumHeight(40)
        actions.addWidget(self.battle_button)
        actions.addStretch()
        self.start = button("开始运行", lambda: self.launch("run"), True)
        self.start.setMinimumSize(144, 40)
        self.monitor_btn = button("耳返自测", self.toggle_monitor)
        self.monitor_btn.setEnabled(False)
        self.mute = button("静音", self.toggle_mute)
        self.stop = button("停止", self.stop_worker)
        self.mute.setEnabled(False)
        self.stop.setEnabled(False)
        actions.addWidget(self.start)
        actions.addWidget(self.monitor_btn)
        actions.addWidget(self.mute)
        actions.addWidget(self.stop)
        self.stack.addWidget(self.scroll_page(page, 185))

    def _driver_page(self):
        p = QWidget()
        box = QVBoxLayout(p)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(11)
        columns = QHBoxLayout()
        columns.setSpacing(11)
        route, rl = panel("设备")
        rl.addWidget(label("输入", "muted"))
        self.input_combo = DeviceCombo()
        self.input_combo.setFixedHeight(40)
        self.input_combo.setAccessibleName("输入麦克风")
        self.input_combo.currentIndexChanged.connect(lambda: self._remember_device("input"))
        rl.addWidget(self.input_combo)
        rl.addSpacing(5)
        rl.addWidget(label("输出", "muted"))
        self.output_combo = DeviceCombo()
        self.output_combo.setFixedHeight(40)
        self.output_combo.setAccessibleName("虚拟声卡播放端")
        self.output_combo.currentIndexChanged.connect(lambda: self._remember_device("output"))
        rl.addWidget(self.output_combo)
        route_footer = QHBoxLayout()
        route_footer.addWidget(label("游戏麦克风：CABLE Output", "muted"))
        route_footer.addStretch()
        self.refresh = button("刷新", self.refresh_devices)
        self.refresh.setObjectName("link")
        route_footer.addWidget(self.refresh)
        rl.addLayout(route_footer)
        columns.addWidget(route, 5)
        voice, vl = panel("目标声线")
        self.voice_status = label("尚未录入", "status")
        vl.addWidget(self.voice_status)
        vl.addStretch()
        self.enroll = button("录入声线 / 6 秒", self.record_voice)
        vl.addWidget(self.enroll)
        small = QHBoxLayout()
        self.import_voice = button("导入", self.import_wav)
        self.forget = button("删除", self.forget_voice)
        small.addWidget(self.import_voice)
        small.addWidget(self.forget)
        vl.addLayout(small)
        vl.addWidget(label("本地加密存储", "muted"))
        columns.addWidget(voice, 3)
        box.addLayout(columns)
        benchmark, bl = panel("线路测速")
        bench_row = QHBoxLayout()
        self.bench_summary = label("尚未测试", "status", True)
        bench_row.addWidget(self.bench_summary, 1)
        self.bench_button = button("重新测速", lambda: self.launch("benchmark"))
        bench_row.addWidget(self.bench_button)
        bl.addLayout(bench_row)
        bl.addWidget(label("点击开始运行时自动测速，切换模式不重测；设备或游戏负载变化后可手动重测", "muted", True))
        box.addWidget(benchmark)
        f, l = panel("VB-CABLE")
        self.driver_status = label("待检测", "status", True)
        l.addWidget(self.driver_status)
        l.addSpacing(10)
        driver_actions = QHBoxLayout()
        self.driver_install = button("安装 / 更新", lambda: self.launch("driver_install"), True)
        self.driver_check = button("检查更新", lambda: self.launch("driver_check"))
        driver_actions.addWidget(self.driver_install)
        driver_actions.addWidget(self.driver_check)
        driver_actions.addStretch()
        l.addLayout(driver_actions)
        l.addSpacing(10)
        self.auto_driver = QCheckBox("检查更新并提醒")
        self.auto_driver.setChecked(self.settings.get("check_driver_updates", True))
        self.auto_driver.toggled.connect(lambda value: self.save_setting("check_driver_updates", value))
        l.addWidget(self.auto_driver)
        l.addWidget(label("安装可能需要管理员权限与重启。", "muted"))
        l.addSpacing(16)
        l.addWidget(label("VB-Audio Donationware，欢迎支持。", "muted"))
        links = QHBoxLayout()
        for text, url in (("VB-CABLE 官网", "https://vb-audio.com/Cable/"),
                          ("许可与支持", "https://vb-audio.com/Services/licensing.htm")):
            link = button(text, lambda checked=False, target=url: QDesktopServices.openUrl(QUrl(target)))
            link.setObjectName("link")
            links.addWidget(link)
        links.addStretch()
        l.addLayout(links)
        box.addWidget(f)
        f2, l2 = panel("维护")
        maintenance = QHBoxLayout()
        self.prepare = button("校验模型", lambda: self.launch("prepare"))
        maintenance.addWidget(self.prepare)
        maintenance.addWidget(button("诊断文件", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))))
        self.licenses_button = button("开源许可", self.open_licenses)
        maintenance.addWidget(self.licenses_button)
        maintenance.addStretch()
        l2.addLayout(maintenance)
        l2.addWidget(label("界面：Qt / PySide6 6.12.0 · LGPLv3", "muted"))
        box.addWidget(f2)
        box.addStretch()
        self.stack.addWidget(self.scroll_page(p, 430))

    def open_licenses(self):
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        page = root / "vendor" / "redistribution" / "QT_PYSIDE_NOTICE.html"
        if not page.is_file():
            self.message.setText("开源许可文件缺失，请重新完整解压程序。")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(page))):
            self.message.setText("无法打开许可说明，请查看程序内 vendor/redistribution 目录。")

    def scroll_page(self, widget, height):
        widget.setObjectName("contentPage")
        widget.setMinimumHeight(max(height, widget.minimumSizeHint().height()))
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(widget)
        return scroll

    def _make_tray(self):
        self.setWindowIcon(app_icon())
        self.tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu()
        menu.addAction("显示 KeepQuiet", self.restore_window)
        menu.addAction("静音／恢复", self.toggle_mute)
        menu.addAction("退出", self.exit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore_window()

    def page(self, index):
        self.stack.setCurrentIndex(index)
        self.controls.setVisible(index == 0)
        if index != 0:
            self.custom_dialog.hide()
        for i, nav in enumerate(self.nav):
            nav.setChecked(i == index)
        self._refresh_icons()
        self._sync_metering()

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.save_setting("theme", self.theme)
        self._apply_theme()

    def _apply_theme(self):
        configure_app(QApplication.instance(), self.theme)
        light = self.theme == "light"
        self.signal.light = light
        self.signal.update()
        for combo in (self.input_combo, self.output_combo, self.purity_combo):
            combo.light = light
            combo.update()
            combo.view().viewport().update()
        self._refresh_icons()
        self.theme_button.setIcon(pixel_icon("moon" if light else "sun", white=not light))
        self.theme_button.setIconSize(QSize(18, 18))
        self.theme_button.setAccessibleName("切换到黑色界面" if light else "切换到白色界面")
        if self.last_error and self.message.styleSheet():
            self._set_error_style()

    def _refresh_icons(self):
        light = self.theme == "light"
        for control in self.findChildren(QPushButton):
            glyph = control.property("glyph_name")
            if glyph:
                white = not light or (control.isEnabled() and (
                    control.objectName() == "primary" or (
                        control.objectName() == "navTop" and control.isChecked())))
                control.setIcon(pixel_icon(glyph, white=white))

    def _set_error_style(self):
        foreground = "#111111" if self.theme == "light" else "#FFFFFF"
        background = "#FFFFFF" if self.theme == "light" else "#000000"
        self.message.setStyleSheet(
            f"color:{foreground};background:{background};border-left:2px solid #2868FF;padding:7px 10px;")

    def _sync_metering(self, force=False):
        active = (self.running and self.isVisible() and not self.isMinimized()
                  and self.stack.currentIndex() == 0)
        self.signal.set_visual_active(active)
        if hasattr(self, "timer"):
            self.timer.setInterval(16 if active else 100)
        if self.conn and self.running and (force or active != self._metering_enabled):
            try:
                self.conn.send({"command": "metering", "value": active})
            except (BrokenPipeError, OSError):
                pass
        self._metering_enabled = active

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "signal"):
            self._sync_metering()

    def hideEvent(self, event):
        super().hideEvent(event)
        if hasattr(self, "signal"):
            self._sync_metering()
        if hasattr(self, "custom_dialog"):
            self.custom_dialog.hide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "signal"):
            self._sync_metering()

    def save_setting(self, key, value):
        self.settings[key] = value
        write_json(data_dir()/"settings.json", self.settings)

    def _persist_profile(self):
        self.settings.update({
            "profile_schema": 1,
            "purity_mode": self.purity_mode,
            "filter_mode": self.filter_mode,
            "gate_threshold_db": self.gate_threshold_db,
            "output_gain_db": self.output_gain_db,
            "custom_filter_mode": self.custom_filter_mode,
            "custom_gate_threshold_db": self.custom_gate_threshold_db,
            "custom_output_gain_db": self.custom_output_gain_db,
        })
        write_json(data_dir()/"settings.json", self.settings)

    def _activate_custom(self):
        if self.purity_mode == "custom":
            return
        self.custom_filter_mode = self.filter_mode
        self.custom_gate_threshold_db = self.gate_threshold_db
        self.custom_output_gain_db = self.output_gain_db
        self.purity_mode = "custom"
        self._setting_profile = True
        try:
            self.purity_combo.setCurrentIndex(self.purity_combo.findData("custom"))
        finally:
            self._setting_profile = False
        self.custom_button.setVisible(True)
        self._persist_profile()

    def _open_custom_on_selection(self, index):
        if self.purity_combo.itemData(index) == "custom":
            QTimer.singleShot(0, self.open_custom_dialog)

    def open_custom_dialog(self):
        if self.battle_enabled or self.purity_mode != "custom":
            return
        self.custom_dialog.show()
        self.custom_dialog.raise_()
        self.custom_dialog.activateWindow()

    def _change_custom_filter(self, index):
        if self._setting_profile or index < 0:
            return
        self._activate_custom()
        self.filter_mode = self.custom_dialog.filter_combo.itemData(index)
        self.custom_filter_mode = self.filter_mode
        self._persist_profile()
        if self.running:
            self._request_run_restart()

    def _change_gate_threshold(self, value):
        if self._setting_profile:
            return
        self.gate_threshold_db = int(clamp_floor(value))
        self.gate_slider.setValue(self.gate_threshold_db)
        self.signal.envelope.set_floors((self.gate_threshold_db, self.gate_threshold_db))
        self._activate_custom()
        self.custom_gate_threshold_db = self.gate_threshold_db
        self.gate_save_timer.start()
        if self.running and self.conn:
            try:
                self.conn.send({"command": "gate", "value": {"threshold_db": self.gate_threshold_db}})
            except (BrokenPipeError, OSError):
                pass

    def _save_gate_threshold(self):
        self._persist_profile()

    def _change_output_gain(self, value):
        if self._setting_profile:
            return
        self.output_gain_db = int(clamp_gain(value))
        self.gain_slider.setValue(self.output_gain_db)
        self._activate_custom()
        self.custom_output_gain_db = self.output_gain_db
        self.gain_save_timer.start()
        if self.running and self.conn:
            try:
                self.conn.send({"command": "output_gain", "value": self.output_gain_db})
            except (BrokenPipeError, OSError):
                pass

    def _save_output_gain(self):
        self._persist_profile()

    def _change_purity(self, index):
        if self._setting_profile or index < 0:
            return
        if self.purity_mode == "custom":
            self.custom_gate_threshold_db = self.gate_threshold_db
            self.custom_output_gain_db = self.output_gain_db
        self.purity_mode = self.purity_combo.itemData(index)
        if self.purity_mode == "custom":
            self.gate_threshold_db = self.custom_gate_threshold_db
            self.output_gain_db = self.custom_output_gain_db
            self.filter_mode = "ultra" if self.custom_filter_mode == "ultra" else "balanced"
            self.custom_filter_mode = self.filter_mode
        else:
            self.gate_threshold_db, self.output_gain_db = PURITY_PRESETS[self.purity_mode]
            self.filter_mode = self.purity_mode
        self._setting_profile = True
        try:
            self.gate_slider.setValue(self.gate_threshold_db)
            self.gate_value.setValue(self.gate_threshold_db)
            self.gain_slider.setValue(self.output_gain_db)
            self.gain_value.setValue(self.output_gain_db)
            self.custom_dialog.filter_combo.setCurrentIndex(self.custom_dialog.filter_combo.findData(
                "ultra" if self.filter_mode == "ultra" else "balanced"))
        finally:
            self._setting_profile = False
        self.custom_button.setVisible(self.purity_mode == "custom")
        if self.purity_mode != "custom":
            self.custom_dialog.hide()
        self.signal.envelope.set_floors((self.gate_threshold_db, self.gate_threshold_db))
        self.gate_save_timer.stop()
        self.gain_save_timer.stop()
        self._persist_profile()
        if self.running:
            self._request_run_restart()

    def _reset_metrics(self):
        self.last_stats = {}
        self.cpu_process = None
        self.cpu_ui_process = None
        self.cpu_count = 1
        for key, text in (("cpu", "0.0%"),):
            self.metrics[key].setText(text)

    def _remember_device(self, direction):
        if self._refreshing_devices:
            return
        combo = self.input_combo if direction == "input" else self.output_combo
        identity = combo.currentData(Qt.ItemDataRole.UserRole + 1)
        if identity:
            self.save_setting(direction + "_device", identity)

    def refresh_devices(self):
        if self.proc:
            return
        try:
            # Reset only the UI's PortAudio enumeration, never the audio worker.
            items = devices(refresh=True)
        except Exception as error:
            self.message.setText(f"无法读取音频设备：{error}")
            return
        self._refreshing_devices = True
        missing = []
        try:
            for direction, combo in (("input", self.input_combo), ("output", self.output_combo)):
                saved = self.settings.get(direction + "_device")
                eligible = ([d for d in items if d["inputs"] and not d["virtual"]]
                            if direction == "input" else [d for d in items if d["outputs"] and d["virtual"]])
                eligible.sort(key=lambda d: (d["host"] != "Windows WASAPI", d["id"]))
                combo.clear()
                for d in eligible:
                    combo.addItem(d["name"] + "  /  " + d["host"].replace("Windows ", ""), d["id"])
                    combo.setItemData(combo.count()-1, selection_key(d), Qt.ItemDataRole.UserRole + 1)
                selected = find_selection(eligible, saved) if saved else (eligible[0] if eligible else None)
                combo.setCurrentIndex(combo.findData(selected["id"]) if selected else -1)
                if saved and not selected:
                    missing.append("麦克风" if direction == "input" else "虚拟声卡")
                elif selected and not saved:
                    self.save_setting(direction + "_device", selection_key(selected))
        finally:
            self._refreshing_devices = False
        if missing:
            self.message.setText("未找到上次使用的" + "、".join(missing) + "，请接回设备后点击刷新，或手动选择。")
        elif getattr(self, "_recovering_device", False):
            self.message.setText("设备已重新识别，点击“重新运行”恢复保护。")
        if not self.output_combo.count():
            self.driver_status.setText("未检测到虚拟声卡，请点击安装 / 更新")

    def _update_voice(self):
        ready = (data_dir()/"voiceprint.protected").exists()
        self.voice_status.setText("已录入" if ready else "未录入")
        self.forget.setEnabled(ready and not self.proc)

    def first_run(self):
        if getattr(self, "screenshot_mode", False):
            return
        if self.auto_driver.isChecked() and not self.proc:
            if not self.output_combo.count():
                self.message.setText("未检测到虚拟声卡，请到设备管理手动安装 VB-CABLE。")
            elif time.time() - self.settings.get("last_driver_check", 0) > 7*86400:
                self.launch("driver_check")

    def record_voice(self):
        if self.enrollment_dialog:
            self.enrollment_dialog.raise_()
            return
        self.enrollment_dialog = EnrollmentDialog(self)
        self.enrollment_dialog.finished.connect(lambda _: setattr(self, "enrollment_dialog", None))
        self.enrollment_dialog.open()

    def import_wav(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入目标声线", "", "PCM WAV (*.wav)")
        if path:
            self.launch("enroll", wav=path)

    def forget_voice(self):
        if self.proc:
            return
        forget_voiceprint()
        self._update_voice()
        self.message.setText("声线已删除")

    def set_busy(self, busy):
        for widget in (self.enroll, self.import_voice, self.forget, self.start,
                       self.bench_button, self.prepare, self.driver_install, self.driver_check,
                       self.input_combo, self.output_combo, self.refresh):
            widget.setEnabled(not busy)
        self.stop.setEnabled(busy and self.operation not in ("driver_install", "driver_check"))
        self._update_mode_controls()
        self._refresh_icons()

    def _update_mode_controls(self):
        preparing = self.proc is not None and not self.running
        self.battle_button.setEnabled(not preparing)
        self.purity_combo.setEnabled(not preparing and not self.battle_enabled)
        self.custom_button.setEnabled(not preparing)
        for control in (self.gate_slider, self.gate_value, self.gain_slider, self.gain_value,
                        self.custom_dialog.filter_combo):
            control.setEnabled(not preparing)
        # Keep an open custom editor visible while its controls are locked.
        # Mode restarts must not dismiss the window the user just opened.

    def _request_run_restart(self):
        if not self.proc or self._restart_pending or self._active_route is None:
            return
        options = {"muted": self.muted, "monitor": self.monitor_active,
                   "resume_route": dict(self._active_route)}
        self.stop_worker()
        self._restart_pending = True
        self._restart_options = options
        self.running = False
        self.signal.set_running(False)
        self._sync_metering()
        self.set_busy(True)
        self._benchmark_in_progress = False
        self.message.setText("正在切换模式…")
        self.badge.setText("■  切换中")

    def launch(self, mode, **extra):
        if self.proc:
            return
        if mode in ("run", "benchmark", "enroll"):
            self.refresh_devices()
        config = {"input_id": self.input_combo.currentData(), "output_id": self.output_combo.currentData(),
                  "metering": self.isVisible() and not self.isMinimized() and self.stack.currentIndex() == 0,
                  "gate": {"threshold_db": self.gate_threshold_db, "purity": self.filter_mode},
                  "output_gain_db": self.output_gain_db, "battle_mode": self.battle_enabled, **extra}
        if mode in ("run", "benchmark", "enroll") and config["input_id"] is None:
            self.message.setText("请先连接并选择一个麦克风。")
            return
        if mode in ("run", "benchmark") and config["output_id"] is None:
            self.page(1)
            self.message.setText("请先安装 VB-CABLE")
            return
        if mode == "run" and not self.battle_enabled and not (data_dir()/"voiceprint.protected").exists():
            self.message.setText("请先录入目标声线。")
            return
        self.operation = mode
        self._benchmark_in_progress = mode == "benchmark" or (mode == "run" and not config.get("resume_route"))
        if self._benchmark_in_progress:
            self.bench_summary.setText("正在自动测速…" if mode == "run" else "正在测速…")
        self._device_failed = False
        if mode == "run":
            self._reset_metrics()
        self.last_error = None
        self.saw_finished = False
        self.message.setStyleSheet("")
        self.conn, child = mp.get_context("spawn").Pipe()
        self.proc = mp.get_context("spawn").Process(target=worker_entry, args=(mode, config, child), daemon=True)
        self.proc.start()
        child.close()
        self.set_busy(True)
        self.progress.setValue(0)
        self.progress.setVisible(mode != "run")
        self.badge.setText("■  配置中" if "driver" in mode else "■  准备中")
        self.message.setText({"run": "正在准备音频…", "benchmark": "正在测试，输出静音", "prepare": "正在校验模型…", "driver_check": "正在检查更新…", "driver_install": "正在部署，请允许 Windows UAC", "enroll": "录音中，请独自连续说话 6 秒"}[mode])
        self.cpu_process = None
        self.cpu_ui_process = None
        try:
            import psutil
            self.cpu_process = psutil.Process(self.proc.pid)
            self.cpu_ui_process = psutil.Process()
            self.cpu_count = psutil.cpu_count(logical=True) or 1
            self.cpu_process.cpu_percent(None)
            self.cpu_ui_process.cpu_percent(None)
        except Exception:
            pass

    def poll(self):
        if not self.proc:
            return
        try:
            while self.conn.poll():
                event = self.conn.recv()
                self.handle_worker_event(event["kind"], event["value"])
        except (EOFError, OSError):
            pass
        if not self.proc.is_alive():
            self.proc.join(timeout=0)
            if not self.saw_finished and self.proc.exitcode:
                self.last_error = f"工作进程意外退出（{self.proc.exitcode}），音频输出已停止。"
                self.message.setText(self.last_error)
            elif self.operation == "run" and not self.last_error:
                self.message.setText("保护已停止")
            self.proc = None
            self._active_route = None
            if self._benchmark_in_progress:
                self.bench_summary.setText("测速未完成")
                self._benchmark_in_progress = False
            self.conn.close()
            self.conn = None
            self.running = False
            self._reset_metrics()
            self.signal.set_running(False)
            self.signal.set_muted(False)
            self._sync_metering()
            self.mute.setEnabled(False)
            self.monitor_btn.setEnabled(False)
            self.monitor_btn.setText("耳返自测")
            self.monitor_active = False
            self.muted = False
            self.mute.setText("静音")
            self.set_busy(False)
            self._update_voice()
            if self.operation == "enroll" and self.enrollment_dialog:
                self.enrollment_dialog.finish(self.last_error)
            self.progress.setVisible(False)
            self.badge.setText("■  待机")
            if self.operation in ("driver_install", "driver_check"):
                self.refresh_devices()
            if self.operation == "run" and getattr(self, "_device_failed", False):
                self._recovering_device = True
                self.start.setText("重新运行")
                self.refresh_devices()
            if self._restart_pending:
                options = self._restart_options
                self._restart_pending = False
                self._restart_options = {}
                if not self.last_error and not self._exiting:
                    self.launch("run", **options)

    def handle_worker_event(self, kind, value):
        if kind == "device_lost":
            self._device_failed = True
        elif kind == "progress":
            self.message.setText(value["message"])
            if value.get("stage") == "benchmark":
                self._benchmark_in_progress = True
                self.bench_summary.setText(value["message"])
            if self.operation == "enroll" and self.enrollment_dialog:
                self.enrollment_dialog.status.setText(value["message"])
            self.progress.setVisible(True)
            self.progress.setValue(int(value.get("fraction", 0)*1000))
        elif kind == "running":
            self.running = True
            self._active_route = dict(value["route"])
            self.muted = bool(value.get("muted", False))
            self.signal.set_muted(self.muted)
            self.mute.setText("恢复声音" if self.muted else "静音")
            self._update_mode_controls()
            self._recovering_device = False
            self.start.setText("开始运行")
            self.signal.set_running(True)
            self._sync_metering(force=True)
            self.mute.setEnabled(True)
            self.monitor_btn.setEnabled(True)
            self.progress.setVisible(False)
            route = Route(**value["route"])
            self.badge.setText("■  已静音" if self.muted else "■  保护中")
            self.message.setText(route.label)
        elif kind == "stats":
            if not self.running or self.saw_finished or self.last_error:
                return
            self.last_stats = value
            if self.cpu_process:
                try:
                    cpu = self.cpu_process.cpu_percent(None)
                    if self.cpu_ui_process:
                        cpu += self.cpu_ui_process.cpu_percent(None)
                    self.metrics["cpu"].setText(f"{cpu / self.cpu_count:.1f}%")
                except Exception:
                    pass
        elif kind == "levels":
            self.signal.set_levels(value["input_level"], value["output_level"], value.get("at"))
        elif kind == "monitor":
            self.monitor_active = bool(value.get("enabled"))
            self.monitor_btn.setText("关闭耳返" if self.monitor_active else "耳返自测")
            if value.get("error"):
                self.message.setText("无法开启耳返：" + value["error"])
        elif kind == "enrolled":
            self._update_voice()
            self.message.setText("声线已录入")
        elif kind == "benchmark":
            self._benchmark_in_progress = False
            self.show_benchmark(value)
            if value.get("selected"):
                route = Route(**value["selected"]["route"])
                self.message.setText("已选择：" + route.label)
        elif kind == "ready":
            self.message.setText("模型已就绪")
        elif kind == "driver":
            self.last_driver = value
            online_checked = value.get("online_checked", True)
            if online_checked:
                self.save_setting("last_driver_check", time.time())
            state = value.get("state")
            if state == "reboot_required":
                self.driver_status.setText("部署完成，待重启验证")
                self.message.setText("请重启 Windows 后重新打开 KeepQuiet")
            elif not online_checked:
                self.driver_status.setText("无法确认最新驱动版本")
                self.message.setText("未完成联网检查；已校验内置驱动包，可稍后手动重试。")
            elif value.get("available") and state != "current":
                self.driver_status.setText(f"可更新至 {value['version']}")
                self.message.setText("发现新版驱动；需要更新时请手动点击“安装 / 更新”。")
            else:
                installed = value.get("installed") or {}
                version = installed.get("DriverVersion", value["version"])
                self.driver_status.setText(f"{version}  /  无需更新")
                self.message.setText("设备已就绪")
            self.refresh_devices()
        elif kind == "priority":
            if value.get("error"):
                self.message.setText(value["error"])
        elif kind in ("error", "cancelled"):
            if self._benchmark_in_progress:
                self.bench_summary.setText("测速已取消" if kind == "cancelled" else "测速失败")
                self._benchmark_in_progress = False
            self._reset_metrics()
            self.last_error = str(value)
            self.message.setText(str(value))
            if kind == "error":
                self._set_error_style()
        elif kind == "finished":
            self.saw_finished = True
            self._reset_metrics()

    def show_benchmark(self, report):
        selected = report.get("selected")
        if selected:
            route = Route(**selected["route"]).label
            delay = selected.get("stats", {}).get("estimated_local_ms")
            self.bench_summary.setText(f"{route} · 本地约 {delay:.0f} ms" if delay is not None else route)
        else:
            self.bench_summary.setText("尚无稳定方案")

    def _toggle_battle_mode(self):
        self.battle_enabled = self.battle_button.isChecked()
        self.purity_combo.set_battle_locked(self.battle_enabled)
        self.custom_button.setVisible(not self.battle_enabled and self.purity_mode == "custom")
        if self.battle_enabled:
            self.custom_dialog.hide()
        if self.running:
            self._request_run_restart()
        if not self._restart_pending:
            self.message.setText("战斗模式已开启" if self.battle_enabled else "战斗模式已关闭")

    def toggle_mute(self):
        if self.running and self.conn:
            self.muted = not self.muted
            self.signal.set_muted(self.muted)
            self.conn.send({"command": "mute", "value": self.muted})
            self.mute.setText("恢复声音" if self.muted else "静音")
            self.badge.setText("■  已静音" if self.muted else "■  保护中")

    def toggle_monitor(self):
        if self.running and self.conn:
            self.conn.send({"command": "monitor", "value": not self.monitor_active})

    def stop_worker(self):
        self._restart_pending = False
        self._restart_options = {}
        if self.conn:
            try:
                self.conn.send({"command": "stop"})
                self.stop.setEnabled(False)
                self.message.setText("正在停止…")
            except (BrokenPipeError, OSError):
                pass

    def exit_app(self):
        if self._exiting:
            return
        if self.gate_save_timer.isActive():
            self.gate_save_timer.stop()
            self._save_gate_threshold()
        if self.gain_save_timer.isActive():
            self.gain_save_timer.stop()
            self._save_output_gain()
        if self.operation == "driver_install" and self.proc and self.proc.is_alive():
            self.message.setText("声卡部署正在完成，请稍后退出。")
            self.restore_window()
            return
        self._exiting = True
        if self.proc:
            self.stop_worker()
            self.proc.join(timeout=2)
            if self.proc.is_alive():
                self.proc.terminate()
                self.proc.join(timeout=1)
        self.tray.hide()
        self.close()
        QApplication.quit()

    def closeEvent(self, event):
        if self._exiting:
            event.accept()
            return
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage("KeepQuiet 已在后台运行", "点击托盘图标恢复界面；右键图标可退出。",
                                      QSystemTrayIcon.MessageIcon.Information, 3000)
        else:
            self.showMinimized()
        event.ignore()


def main(screenshot=None):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("KeepQuiet")
    configure_app(app)
    lock = QLockFile(str(data_dir()/"app.lock"))
    if not lock.tryLock(0):
        QMessageBox.information(None, "KeepQuiet", "KeepQuiet 已在运行，请从系统托盘打开。")
        return 0
    window = Window()
    window.show()
    if sys.platform == "win32":
        try:
            import ctypes
            enabled = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(int(window.winId())), 20, ctypes.byref(enabled), 4)
        except (OSError, AttributeError):
            pass
    if screenshot:
        # Offline UI review: no automatic device actions during screenshots.
        window.screenshot_mode = True
        QTimer.singleShot(350, lambda: (window.grab().save(str(screenshot)), window.exit_app()))
    return app.exec()
