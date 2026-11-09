# 构建与测试

## 环境

本地已验证 Windows x64 / Python 3.12。依赖以 pyproject.toml 的固定版本为准。仓库包含 Focus/Cue/Timbre 模型、许可和原始基础 VB-CABLE 包；无需把本机虚拟环境或已打包 DLL 提交到 Git。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Setup.ps1
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build.ps1 -OutputDirectory dist-github
```

Build 会先运行测试再打包。dist-github 中的 ZIP 顶层为 KeepQuiet、Install-KeepQuiet.ps1 、README.md、THIRD_PARTY_NOTICES.md 、LICENSE_STATUS.md 与 LICENSE；SHA256SUMS.txt 记录散列。发布时将 ZIP 和校验文件放到 GitHub Releases，源码树不加入 dist 或 build。

## 无真实音频端点的机器

CI 使用以下命令保留离线模型、DPAPI、UI 状态和模拟音频测试，仅排除依赖宿主真实音频端点的注册表测试：

```powershell
python -B -m pytest -q -p no:cacheprovider -k "not test_fast_registry_queries_avoid_spawning_powershell_on_windows"
```

如需在同类机器执行 Build，可先设置：

```powershell
$env:PYTEST_ADDOPTS = '-k "not test_fast_registry_queries_avoid_spawning_powershell_on_windows"'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build.ps1 -OutputDirectory dist-github
Remove-Item Env:PYTEST_ADDOPTS
```

原生截图脚本必须在可交互 Windows 桌面运行，并指定独立 KEEPQUIET_DATA_DIR；不要对实际用户配置生成公开截图。GitHub CI 未执行真实麦克风／游戏链路，也没有自动安装驱动或发布 Release。

## 第三方材料

原始 VB-CABLE 包 SHA-256 固定且在安装前另做签名校验。只包含基础包，保留用户可见的 VB-Audio 来源和 Donationware 支持信息。发布 Qt/PySide 二进制时核对实际组件的许可义务及对应源码材料，见根目录 THIRD_PARTY_NOTICES.md。

## Qt / PySide 对应源码附件

Build 会执行 scripts/Prepare-QtSources.py，从 vendor/redistribution/qt-pyside-manifest.json 中的官方 URL 获取两个固定 SHA256 的源码档案；首次构建需要网络，验证过的缓存位于 build/qt-sources-cache。随后生成 KeepQuiet-Qt-PySide-6.12.0-source.zip，与成品共用 dist-github/SHA256SUMS.txt。此附件必须与成品在同一 Release 提供并保持下载可用，不必提交大型源码档案到 Git 仓库。原始许可、声明、版本来源与替换说明随应用 vendor 目录打包，安装后保留。
