# Native one-directory build: fast launch; Qt DLLs remain separately replaceable.
from pathlib import Path
root = Path(SPECPATH)
datas = [(str(root/'models'), 'models'), (str(root/'vendor'), 'vendor'),
         (str(root/'scripts'/'Install-VBCable.ps1'), 'scripts')]
a = Analysis([str(root/'launch.py')], pathex=[str(root)], binaries=[], datas=datas,
    hiddenimports=['_sounddevice_data', 'alkove._alkove'],
    excludes=['tkinter','onnxruntime','torch','scipy','matplotlib','pandas',
              'PySide6.QtNetwork','PySide6.QtQml','PySide6.QtQuick',
              'PySide6.QtOpenGL','PySide6.QtTest','PySide6.QtSql','PySide6.QtSvg'],
    noarchive=False)

_DROP_BINARIES = {
    'opengl32sw.dll', 'qt6network.dll', 'qt6svg.dll',
    'qsvg.dll', 'qsvgicon.dll', 'qtiff.dll', 'qwebp.dll', 'qjpeg.dll',
    'qicns.dll', 'qtga.dll', 'qwbmp.dll', 'qgif.dll',
    'qdirect2d.dll', 'qtuiotouchplugin.dll',
    'libportaudio.dylib', 'libportaudio32bit.dll', 'libportaudio32bit-asio.dll',
    'libportaudio64bit-asio.dll', 'libportaudioarm64.dll', 'libportaudioarm64-asio.dll',
}
a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in _DROP_BINARIES]
a.datas = [
    d for d in a.datas
    if Path(d[0]).name.lower() not in _DROP_BINARIES
    and 'PySide6/translations' not in d[0].replace('\\', '/')
]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='KeepQuiet',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
    icon=str(root/'assets'/'KeepQuiet.ico'), version=str(root/'scripts'/'version-info.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='KeepQuiet')
