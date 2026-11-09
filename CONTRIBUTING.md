# 开发说明

先阅读 README、docs/ARCHITECTURE.md 和 docs/VALIDATION.md。建议使用 Windows x64、Python 3.12 与独立虚拟环境。

修复音频问题时，同时检查目标声音损伤、串音、CPU、延迟、欠载和停止恢复。模型与驱动保持可追溯版本及原始许可。提交测试时使用合成音频或有明确许可的公开样本；真实声纹、私人录音、settings.json 和设备诊断不要加入仓库。

运行 `python -B -m pytest -q -p no:cacheprovider`。需要原生 UI 检查时，为该次命令指定独立数据目录：

```powershell
$env:KEEPQUIET_DATA_DIR = Join-Path $env:TEMP ('KeepQuiet-review-' + [guid]::NewGuid().ToString('N'))
python -B scripts/Review-Pixel.py
python -B scripts/Verify-Background.py
Remove-Item Env:KEEPQUIET_DATA_DIR
```

CI 只排除 `test_fast_registry_queries_avoid_spawning_powershell_on_windows`，因为它断言宿主具有音频端点。不要在无声卡 runner 上用该项替代真实硬件验收。

模式切换经停止、沿用当前线路和新进程启动；只有点击开始运行或手动重新测速时测速；准备期间锁定参数。普通模式遇到无效声纹应停止输出；战斗原声必须由用户显式启用。

原创实现采用 MIT 许可。提交原创贡献即表示有权将该贡献按项目 MIT 许可提供；第三方内容须保留其来源与原有许可。
