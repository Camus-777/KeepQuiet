# Third-party notices

KeepQuiet's original implementation is licensed under the MIT License (see LICENSE). Third-party components retain their own licenses; the project's MIT License does not relicense them.

| Component | Version / files | License and source |
| --- | --- | --- |
| Alkove native engine | 0.4.0 dependency | Apache-2.0; https://github.com/alkove-ai/alkove/tree/v0.4.0 |
| Focus, Cue, Timbre model files | Pinned hashes in models/manifest.json | Original Apache-2.0 license and upstream notices retained in models/ALKOVE-LICENSE.txt and models/ALKOVE-NOTICE.txt |
| Public test WAV fixtures | tests/fixtures | Upstream provenance in tests/fixtures/NOTICE.txt; not a saved user voice identity |
| NumPy | 2.5.4 | BSD and bundled notices; vendor/licenses/numpy |
| python-sounddevice / PortAudio | 0.5.6 | MIT; vendor/licenses/sounddevice |
| PySide6 Essentials / Qt / Shiboken6 | 6.12.0 | LGPL/GPL/commercial terms depend on components; vendor/licenses contains original texts; https://doc.qt.io/qtforpython-6/licenses.html |
| psutil | 7.2.2 | BSD-3-Clause; vendor/licenses/psutil |
| CFFI | Dependency | MIT; https://cffi.readthedocs.io/ |
| CPython | Runtime | PSF license; https://www.python.org/ |
| PyInstaller | 6.22.3 build tool | GPL with bootloader exception; https://pyinstaller.org/ |
| VB-CABLE base Pack45 | Unmodified vendor/vbcable/VBCABLE_Driver_Pack45.zip | VB-Audio proprietary Donationware; https://vb-audio.com/Services/licensing.htm |

## VB-CABLE

VB-CABLE is an independent VB-Audio / Vincent Burel product. Origin: https://www.vb-cable.com/ . It is Donationware; all participations are welcome. Support/license: https://shop.vb-audio.com/en/win-apps/11-vb-cable.html .

Only the original base package is included AS IS. A+B and C+D are excluded. Its original readme and license remain inside the unchanged ZIP. The current vendor distribution conditions, including attribution and professional deployment conditions, are at https://vb-audio.com/Services/licensing.htm (reviewed 2026-11-09). Keep this notice and the visible in-app attribution when distributing.

## Qt / PySide / Shiboken distribution

The LGPL-3.0-only option is selected for the shipped Qt 6.12.0 Core/Gui/Widgets libraries and Qt Base plugins, PySide6 Essentials 6.12.0 and Shiboken6 6.12.0. Third-party code inside these libraries retains its own license. Original commercial-alternative texts are retained without selecting the commercial option.

All 14 retained Qt/PySide/Shiboken binary files match the official PyPI Windows x64 wheels byte for byte. Exact URLs, hashes, metadata licensing and the file inventory are in vendor/redistribution/qt-pyside-manifest.json. No retained library binaries have been locally modified. Microsoft Visual C++ runtime files are separate platform-runtime components and are not relicensed under LGPL.

Original license texts and attribution files from the exact upstream source releases are retained under vendor/licenses/Qt/upstream and vendor/licenses/QtForPython/upstream. See vendor/redistribution/QT_THIRD_PARTY_ATTRIBUTIONS.md for the conservative upstream attribution index. Runtime paths begin with KeepQuiet/_internal/ in a portable release; the optional installer keeps these files.

Publish **KeepQuiet-Qt-PySide-6.12.0-source.zip** at the same GitHub Release download location as the Windows binary. It provides the complete, unmodified Qt Base and Qt for Python 6.12.0 source archives, source checksums, provenance, original build scripts and rebuilding/replacement instructions. Keep the source download available while distributing the corresponding binary. The source-package workflow uses accompanying network source access, not an unfulfilled written offer.

Users may modify and replace these externally loaded libraries, including reverse engineering needed to debug their modifications. The application places no runtime signature/hash lock, installation-key requirement or additional license restriction on Qt/PySide replacements. See vendor/redistribution/REBUILD_AND_REPLACE.md for ABI requirements and paths. The in-app settings page identifies Qt/PySide and provides an offline license page.

References:
- https://www.qt.io/development/open-source-lgpl-obligations
- https://doc.qt.io/qtforpython-6/licenses.html
- https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/
- https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/
