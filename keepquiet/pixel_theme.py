"""Black, white and blue UI tokens; crisp monochrome pixel symbols."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

INK = '#FFFFFF'
BLUE = '#2868FF'

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; color: #FFFFFF; }
QMainWindow, QDialog, #main, #contentPage { background: #000000; }
QScrollArea { border: none; background: #000000; }
#brand { color: #FFFFFF; font-family: 'Consolas'; font-size: 18px; font-weight: 700; }
QPushButton { background: #000000; border: 1px solid #FFFFFF; border-radius: 0;
    padding: 8px 14px; font-weight: 500; }
QPushButton:hover { background: #202020; }
QPushButton:pressed { background: #3D3D3D; }
QPushButton:disabled { color: #878787; background: #151515; border-color: #3D3D3D; }
QPushButton#primary { background: #2868FF; color: #FFFFFF; border: 1px solid #2868FF; font-weight: 600; }
QPushButton#primary:hover { background: #0046DA; border-color: #0046DA; }
QPushButton#primary:pressed { background: #0036AE; }
QPushButton#primary:disabled { color: #777777; background: #151515; border-color: #3D3D3D; }
QPushButton#navTop { color: #FFFFFF; background: #000000; border: 1px solid #FFFFFF; padding: 7px 9px; }
QPushButton#navTop:hover { background: #202020; }
QPushButton#navTop:checked { color: #FFFFFF; background: #2868FF; border-color: #2868FF; }
QPushButton#link { color: #2868FF; background: transparent; border: none; padding: 5px 0; text-align: left; }
QPushButton#link:hover { text-decoration: underline; }
QPushButton#battleMode { background: transparent; border: 1px solid #FFFFFF; }
QPushButton#battleMode:hover { background: transparent; }
QPushButton#battleMode:checked { background: #D12D3C; color: #FFFFFF; border-color: #D12D3C; }
#dialogTitle { font-size: 20px; font-weight: 700; }
#helpDot { color: #FFFFFF; background: #000000; border: 1px solid #FFFFFF; border-radius: 8px; font-size: 11px; font-weight: 700; }
#helpPopup { color: #000000; background: #FFFFFF; border: 1px solid #000000; padding: 8px; }
#muted { color: #AAAAAA; }
#panel { background: #000000; border: 1px solid #555555; border-radius: 0; }
#panelTitle { font-size: 14px; font-weight: 700; padding-bottom: 4px; }
#footerMetric { color: #AAAAAA; font-family: 'Consolas'; font-size: 12px; font-weight: 400; }
#badge { color: #FFFFFF; background: #000000; border: 1px solid #FFFFFF; border-radius: 0; padding: 8px 14px; }
#status { color: #2868FF; font-weight: 600; }
#message { color: #AAAAAA; padding: 1px 0; font-size: 12px; }
#actionBar { border-top: 2px solid #FFFFFF; }
QComboBox { background: #000000; border: 1px solid #AAAAAA; border-radius: 0; padding: 7px 28px 7px 10px; min-height: 22px; }
QComboBox:hover, QComboBox:focus { border: 1px solid #2868FF; }
QComboBox:disabled { color: #878787; border-color: #3D3D3D; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView { background: #000000; border: 1px solid #FFFFFF; selection-background-color: #2868FF; selection-color: #FFFFFF; color: #FFFFFF; padding: 5px; }
QComboBox QAbstractItemView::item:hover { background: #2868FF; color: #FFFFFF; }
QProgressBar { background: #3D3D3D; border: none; border-radius: 0; height: 4px; }
QProgressBar::chunk { background: #2868FF; border-radius: 0; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QSlider::groove:horizontal { height: 4px; background: #3D3D3D; border-radius: 0; }
QSlider::sub-page:horizontal { background: #2868FF; border-radius: 0; }
QSlider::handle:horizontal { width: 12px; margin: -5px 0; background: #FFFFFF; border: 1px solid #FFFFFF; border-radius: 0; }
QSlider::handle:horizontal:hover { background: #2868FF; }
QMenu { background: #000000; color: #FFFFFF; border: 1px solid #FFFFFF; padding: 4px; }
QMenu::item { padding: 8px 18px; }
QMenu::item:selected { background: #2868FF; color: #FFFFFF; }
QScrollBar:vertical { background: #202020; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #FFFFFF; min-height: 30px; border-radius: 0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #FFFFFF; color: #000000; border: 1px solid #000000; padding: 8px; }
"""


def style_for_theme(theme):
    if theme != 'light':
        return STYLE
    colors = {
        '#000000': '#FFFFFF', '#FFFFFF': '#111111', '#202020': '#F2F2F2',
        '#3D3D3D': '#CCCCCC', '#555555': '#B8B8B8', '#AAAAAA': '#666666',
        '#BDBDBD': '#555555', '#878787': '#777777', '#151515': '#ECECEC',
    }
    result = STYLE
    for index, source in enumerate(colors):
        result = result.replace(source, f'@COLOR{index}@')
    for index, target in enumerate(colors.values()):
        result = result.replace(f'@COLOR{index}@', target)
    return result + """
QPushButton#primary, QPushButton#navTop:checked, QPushButton#battleMode:checked, QMenu::item:selected,
QComboBox QAbstractItemView::item:hover { color: #FFFFFF; }
QComboBox QAbstractItemView { selection-color: #FFFFFF; }
"""

# Nine-unit symbols snap to whole pixels at the common 18/36 px sizes.
GLYPHS = {
    'mic': ['000111000','001111100','001111100','001111100','101111101','100111001','011111110','000010000','001111100'],
    'filter': ['000010000','001010100','101010101','101010101','101010101','101010101','101010101','001010100','000010000'],
    'cable': ['111111111','100000001','101010101','101010101','101010101','100000001','111111111','001000100','001111100'],
    'control': ['001000000','111111111','001000000','000000100','111111111','000000100','000100000','111111111','000100000'],
    'pulse': ['000000000','000100000','000110000','001010100','111010111','000011000','000010000','000000000','000000000'],
    'devices': ['111111111','100000001','100000001','100000001','111111111','000010000','001111100','000000000','110110110'],
    'play': ['001000000','001100000','001110000','001111000','001111100','001111000','001110000','001100000','001000000'],
    'stop': ['000000000','011111110','011111110','011111110','011111110','011111110','011111110','011111110','000000000'],
    'mute': ['000100000','001100000','111101010','111100100','111101010','001100000','000100000','000000000','000000000'],
    'record': ['000111000','001111100','011111110','111111111','111111111','111111111','011111110','001111100','000111000'],
    'import': ['000010000','000010000','001010100','000111000','000010000','000000000','100000001','100000001','111111111'],
    'trash': ['000111000','111111111','001000100','001010100','001010100','001010100','001000100','001111100','000000000'],
    'refresh': ['001111101','010000011','100000111','100000000','100000001','000000001','111000001','110000010','101111100'],
    'sun': ['000010000','010010010','001111100','001111100','111111111','001111100','001111100','010010010','000010000'],
    'moon': ['001111000','011110000','111100000','111100000','111100000','111110001','011111110','001111100','000111000'],
}


def draw_glyph(painter, name, x, y, unit=2, color='#000000'):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    for row, bits in enumerate(GLYPHS[name]):
        for col, bit in enumerate(bits):
            if bit == '1':
                painter.fillRect(round(x + col*unit), round(y + row*unit), unit, unit, QColor(color))
    painter.restore()


def pixel_icon(name='filter', white=False):
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    draw_glyph(painter, name, 0, 0, color='#FFFFFF' if white else '#000000')
    painter.end()
    icon = QIcon(pix)
    # Disabled icons remain grayscale, never acquire a platform accent tint.
    icon.addPixmap(pix, QIcon.Mode.Disabled)
    return icon


def app_icon():
    pix = QPixmap(64, 64)
    pix.fill(QColor('#000000'))
    painter = QPainter(pix)
    draw_glyph(painter, 'filter', 14, 14, 4, '#FFFFFF')
    painter.end()
    return QIcon(pix)
