# KeepQuiet 0.2.2

Windows x64 本地目标声线提取与虚拟麦克风工具。

## 使用

1. 完整解压，运行 `KeepQuiet/KeepQuiet.exe`；不需要安装 Python。
2. 在设备管理中检查 VB-CABLE。安装驱动需主动操作，可能需要管理员权限及重启。
3. 输入选择物理麦克风，输出选择 CABLE Input；游戏或聊天软件选择 CABLE Output。
4. 普通降噪先录入目标声线，再选择档位并点击“开始运行”；点击开始运行时自动测速，运行中切换模式不重测。
5. 关闭窗口会保留在系统托盘；彻底退出请使用托盘菜单。

可选：运行 `Install-KeepQuiet.ps1`，将完整程序复制到当前用户的 Programs/KeepQuiet 并创建开始菜单快捷方式；便携运行无需执行此脚本。

## 模式与边界

普通模式提供三档和自定义。战斗模式绕过降噪模型，直接处理麦克风原声，周围人声也会进入失真效果。两者参数独立。

多人同时说话、混响和轻声仍可能导致串音或音质损伤。CPU 与实际游戏负载有关；尚未验证反作弊兼容性、长时间游戏链路和目标电脑的主观音质。

## 许可与来源

原创代码采用 MIT 许可，完整文本见 `LICENSE`，适用范围见 `LICENSE_STATUS.md`。第三方说明见 `THIRD_PARTY_NOTICES.md`；原始许可保存在 `KeepQuiet/_internal/vendor/licenses/`，模型许可在 `KeepQuiet/_internal/models/`。界面组件 Qt/PySide/Shiboken 6.12.0 选择 LGPLv3；在“设备管理 → 维护 → 开源许可”可离线查看许可与替换说明。对应源码在同一 Release 的 KeepQuiet-Qt-PySide-6.12.0-source.zip 免费下载。发布者必须将该源码附件与本成品一起提供，保留可用下载。根目录 QT_PYSIDE_NOTICE.md 和 REBUILD_AND_REPLACE.md 提供详细说明。

VB-CABLE 是 VB-Audio 的独立 Donationware 产品，欢迎支持：[官方网站](https://www.vb-cable.com/) · [许可与支持](https://vb-audio.com/Services/licensing.htm)。随附基础供应商 ZIP 保持原样，不包含 A+B、C+D。

版本 0.2.2；本次修订基于 battle-fix5，项目名称统一为 KeepQuiet。
