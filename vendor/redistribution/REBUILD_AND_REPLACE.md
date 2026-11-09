# Qt / PySide6 6.12.0 构建与动态库替换

## 当前版本与源码

Windows x64；Qt 6.12.0 动态 release 构建，MSVC 2022；PySide6 Essentials 和 Shiboken6 6.12.0 为 cp310-abi3-win_amd64 官方 wheel。应用当前使用 Python 3.12。对应源码 ZIP 包含未经修改的 qtbase-everywhere-src-6.12.0.tar.xz 和 pyside-setup-everywhere-src-6.12.0.tar.xz。每个包包含原始构建脚本、头文件、源文件和许可证；SHA256 与来源见 qt-pyside-manifest.json。

本地没有修改 Qt/PySide/Shiboken 代码。官方二进制的字节级匹配记录见同一 manifest。这里给出兼容性重建入口，不宣称重新编译所得字节必然与官方构建完全相同，也不以官方哈希阻止用户使用修改后的库。

## 构建工具

使用 x64 Native Tools Command Prompt for Visual Studio 2022 或等效开发者 PowerShell，安装 MSVC C++、Windows SDK、CMake、Ninja 和 Python。PySide/Shiboken 生成绑定还需要 libclang；本版本上游 README.pyside6.md 指定的 Windows libclang 构建系列为 LLVM 22.1.8 / vs2022_64，设置 LLVM_INSTALL_DIR 指向解压目录。工具及其源码获取入口由上游 README、configure 和 setup.py 提供。构建工具本身不随 KeepQuiet 运行时分发。

## Qt Base

解压两个源码包，在独立空目录构建 Qt Base。例如（开发者 PowerShell）：

```powershell
$qtSource = (Resolve-Path '.\qtbase-everywhere-src-6.12.0').Path
$qtPrefix = Join-Path $PWD 'qt-install'
New-Item -ItemType Directory -Force qt-build | Out-Null
Push-Location qt-build
& (Join-Path $qtSource 'configure.bat') -release -shared -opensource -confirm-license -nomake examples -nomake tests -prefix $qtPrefix
if ($LASTEXITCODE -ne 0) { throw 'Qt configure failed' }
cmake --build . --parallel
if ($LASTEXITCODE -ne 0) { throw 'Qt build failed' }
cmake --install .
if ($LASTEXITCODE -ne 0) { throw 'Qt install failed' }
Pop-Location
```

所需模块为 QtCore、QtGui、QtWidgets；保留 qwindows 平台插件，以及你使用的 qico、qminimal、qoffscreen、qmodernwindowsstyle 插件。源树 src/3rdparty 和 LICENSES 包含原始依赖及声明。不同工具／可选功能配置可能改变依赖，按该源码包的 configure --help 和原始构建文档设置，不要混用 Debug 与 Release DLL。

## PySide / Shiboken

在与运行环境兼容的 Python 环境和开发者终端中，进入 pyside-setup-everywhere-src-6.12.0。先设置 LLVM_INSTALL_DIR，按上游 requirements.txt 和 README.pyside6.md 配置构建依赖。上游 README 的标准入口是：

```powershell
python setup.py build "--qtpaths=$qtPrefix/bin/qtpaths6.exe" --limited-api=yes "--module-subset=Core,Gui,Widgets"
```

该入口同时构建 Shiboken 与 PySide，原始 setup.py 和 build_scripts 已完整提供。使用上游支持的 --limited-api=yes 生成稳定 ABI 绑定（与当前 cp310-abi3 wheel 的最低 ABI 和目标环境保持兼容）；只构建所需模块可参考上游的 --module-subset=Core,Gui,Widgets。构建／安装选项以该版本源码的帮助及 README 为准。这里未在本次验证中重新编译 Qt 或 PySide 本身。

## 在便携版或安装版替换

1. 从系统托盘彻底退出 KeepQuiet，并备份原应用目录。
2. 在应用目录的 _internal/PySide6/ 中替换 Qt6Core.dll、Qt6Gui.dll、Qt6Widgets.dll，以及需要修改的 QtCore.pyd、QtGui.pyd、QtWidgets.pyd、pyside6.abi3.dll；保持修改所需的同版本绑定与 Qt 成套兼容。
3. 对应平台／图像／样式插件位于 _internal/PySide6/plugins/。替换 libshiboken 时同步更新 _internal/shiboken6/Shiboken.pyd 与 shiboken6.abi3.dll。
4. 保留应用所需的其余文件、Python ABI 及 Microsoft 运行库，启动 KeepQuiet 检查界面和功能。替换路径与清单见 manifest。ABI 不兼容可能导致无法启动，应恢复备份或提供一致的重建组件。

这些库在文件系统中独立分发，没有被封进 KeepQuiet.exe；应用没有针对这些 Qt/PySide 库的运行时签名／哈希限制或安装密钥要求。模型文件的完整性校验与 Qt 库替换无关。项目 MIT 许可与任何说明不限制 LGPL 赋予的修改、重新链接，以及为调试这些修改而进行必要逆向工程的权利。

## 重新分发修改后的库

保留原版权与许可，标明修改并提供你所分发版本的完整对应源码和相关构建／安装信息。不要把原始官方源码附件冒充修改版库的对应源码。KeepQuiet 本身可从 MIT 源码运行和重新打包。
