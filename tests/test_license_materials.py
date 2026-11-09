from pathlib import Path

from test_profiles import make_window, close_window


def test_license_button_opens_installed_offline_notice(tmp_path, monkeypatch):
    from keepquiet import ui
    app, window = make_window(tmp_path, monkeypatch)
    opened = []
    monkeypatch.setattr(ui.QDesktopServices, 'openUrl', lambda url: opened.append(url) or True)
    try:
        window.licenses_button.click()
        assert len(opened) == 1 and opened[0].isLocalFile()
        page = Path(opened[0].toLocalFile())
        assert page.is_file() and page.name == 'QT_PYSIDE_NOTICE.html'
        assert 'LGPLv3' in page.read_text(encoding='utf-8')
        import re
        for href in re.findall(r'href="([^"]+)"', page.read_text(encoding='utf-8')):
            assert (page.parent / href).is_file(), href
    finally:
        close_window(app, window)


def test_missing_license_files_show_error_without_opening_browser(tmp_path, monkeypatch):
    from keepquiet import ui
    app, window = make_window(tmp_path, monkeypatch)
    monkeypatch.setattr(ui.sys, '_MEIPASS', str(tmp_path / 'incomplete-install'), raising=False)
    def forbidden(url):
        raise AssertionError('A missing local license page must not open a browser')
    monkeypatch.setattr(ui.QDesktopServices, 'openUrl', forbidden)
    try:
        window.licenses_button.click()
        assert '许可文件缺失' in window.message.text()
    finally:
        close_window(app, window)
