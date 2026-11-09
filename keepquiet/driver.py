"""VB-CABLE bootstrap/update from VB-Audio, with vendor attribution and signatures."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error

from .storage import data_dir, write_json

OFFICIAL_PAGE = "https://vb-audio.com/Cable/"
OFFICIAL_BASE = "https://download.vb-audio.com/Download_CABLE/"
BUNDLED_NAME = "VBCABLE_Driver_Pack45.zip"
BUNDLED_SHA256 = "b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb"


def shell_runtime():
    # A parent PowerShell 7 can export modules incompatible with Windows PS 5.1.
    # Limit this child to built-in Windows modules and use its absolute binary.
    home = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0"
    env = os.environ.copy()
    env["PSModulePath"] = str(home / "Modules")
    if getattr(sys, "frozen", False):
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    return str(home / "powershell.exe"), env


def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def powershell(script, timeout=40):
    import base64
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    exe, env = shell_runtime()
    result = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, timeout=timeout, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace") or
                           f"PowerShell 返回 {result.returncode}")
    return result.stdout.decode("utf-8-sig").strip()


def _installed_driver_registry():
    if sys.platform != "win32":
        return None
    import winreg
    key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e96c-e325-11ce-bfc1-08002be10318}"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as root:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
                i += 1
            except OSError:
                break
            if not sub.isdigit():
                continue
            try:
                with winreg.OpenKey(root, sub) as k:
                    desc, _ = winreg.QueryValueEx(k, "DriverDesc")
                    if desc == "VB-Audio Virtual Cable":
                        ver, _ = winreg.QueryValueEx(k, "DriverVersion")
                        inf, _ = winreg.QueryValueEx(k, "InfPath")
                        return {"DeviceName": desc, "DriverVersion": ver, "InfName": inf}
            except OSError:
                continue
    return None


def installed_driver():
    try:
        info = _installed_driver_registry()
        if info is not None:
            return info
    except OSError:
        pass
    text = powershell("""
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
@((Get-CimInstance Win32_PnPSignedDriver | Where-Object {
 $_.DeviceName -eq 'VB-Audio Virtual Cable'
} | Select-Object DeviceName, DriverVersion, InfName)) | ConvertTo-Json -Compress
""")
    value = json.loads(text or "[]")
    if isinstance(value, dict):
        value = [value]
    return value[0] if value else None


def package_url(name):
    if not re.fullmatch(r"VBCABLE_Driver_Pack\d+\.zip", name):
        raise ValueError("声卡包名称无效。")
    return OFFICIAL_BASE + name


def official_latest() -> str:
    req = urllib.request.Request(OFFICIAL_PAGE, headers={'User-Agent': 'KeepQuiet/0.1'})
    with urllib.request.urlopen(req, timeout=3.0) as response:
        if urllib.parse.urlsplit(response.url).hostname != 'vb-audio.com':
            raise RuntimeError('官方更新页面发生了未预期的跳转。')
        html = response.read(1000000).decode('utf-8', errors='replace')
    names = re.findall('VBCABLE_Driver_Pack(\\d+)\\.zip', html)
    if not names:
        raise RuntimeError('官网未提供可识别的声卡更新包，请稍后重试。')
    return 'VBCABLE_Driver_Pack' + str(max(map(int, names))) + '.zip'



def stage_package(name=BUNDLED_NAME):
    import zipfile
    source = resource_root() / "vendor" / "vbcable" / name
    target = data_dir() / "driver-packages" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        req = urllib.request.Request(package_url(name), headers={"User-Agent": "KeepQuiet/0.1"})
        with urllib.request.urlopen(req, timeout=40) as response:
            if urllib.parse.urlsplit(response.url).hostname != "download.vb-audio.com":
                raise RuntimeError("声卡包下载地址不属于 VB-Audio。")
            blob = response.read(30_000_001)
            if len(blob) > 30_000_000:
                raise RuntimeError("声卡安装包超过大小限制。")
    else:
        blob = source.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if name == BUNDLED_NAME and digest != BUNDLED_SHA256:
        raise RuntimeError("封装的 VB-CABLE 安装包校验失败。")
    from .storage import atomic_bytes
    atomic_bytes(target, blob)
    with zipfile.ZipFile(target) as archive:
        if sum(x.file_size for x in archive.infolist()) > 80_000_000:
            raise RuntimeError("声卡安装包解压大小异常。")
        names = archive.namelist()
        if any("/" in x or "\\" in x or ":" in x or x in (".", "..") for x in names):
            raise RuntimeError("声卡安装包包含非预期路径。")
        if "VBCABLE_Setup_x64.exe" not in names or "vbMmeCable64_win10.inf" not in names:
            raise RuntimeError("声卡安装包布局已经变化，需更新 KeepQuiet。")
        inf = archive.read("vbMmeCable64_win10.inf").decode("utf-8", errors="replace")
    match = re.search(r"DriverVer\s*=\s*[\d/]+\s*,\s*([\d.]+)", inf)
    if not match:
        raise RuntimeError("无法识别驱动版本。")
    return target, digest, match[1]


def version_tuple(value):
    return tuple(int(p) for p in value.split("."))


def verify_package(path, digest):
    """Run the same Authenticode checks before requesting elevation."""
    result_path = data_dir() / "driver-signatures.json"
    result_path.unlink(missing_ok=True)
    script = resource_root() / "scripts" / "Install-VBCable.ps1"
    exe, env = shell_runtime()
    completed = subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(script), "-Package", str(path), "-ExpectedSha256", digest,
        "-ResultPath", str(result_path), "-VerifyOnly"], capture_output=True,
        timeout=40, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    if not result_path.exists():
        raise RuntimeError("无法完成声卡数字签名校验。")
    result = json.loads(result_path.read_text("utf-8-sig"))
    if completed.returncode or result.get("state") != "verified":
        raise RuntimeError(result.get("error", "声卡数字签名校验失败。"))
    return result


def check_update(online: bool = True) -> dict:
    installed = installed_driver()
    name = BUNDLED_NAME
    online_checked = False
    if online:
        try:
            name = official_latest()
            online_checked = True
        except Exception:
            name = BUNDLED_NAME
    path, digest, version = stage_package(name)
    signature = verify_package(path, digest)
    result = {
        'online_checked': online_checked,
        'installed': installed,
        'package': name,
        'version': version,
        'path': str(path),
        'sha256': digest,
        'source': package_url(name),
        'signature': signature,
        'available': installed is None or version_tuple(installed['DriverVersion']) < version_tuple(version),
    }
    write_json(data_dir() / 'driver-update.json', result)
    return result



def install_driver(online=True, emit=lambda *_: None):
    if platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("此 KeepQuiet 构建仅支持 Windows x64。")
    emit("progress", {"message": "正在检查 VB-CABLE 版本和安装包…", "fraction": .1})
    try:
        info = check_update(online=online)
    except (urllib.error.URLError, TimeoutError):
        if not online:
            raise
        emit("progress", {"message": "官网暂时无法连接，正在校验封装的离线安装包。", "fraction": .2})
        info = check_update(online=False)
    if not info["available"]:
        return {"state": "current", **info}
    script = resource_root() / "scripts" / "Install-VBCable.ps1"
    result_path = data_dir() / "driver-install-result.json"
    result_path.unlink(missing_ok=True)
    # Values are PowerShell single-quoted, then Windows argv-quoted inside the
    # ArgumentList. No shell expansion of a path or network response is allowed.
    def ps_quote(s):
        return "'" + str(s).replace("'", "''") + "'"
    def arg(s):
        return ps_quote('"' + str(s) + '"')
    args = [ps_quote("-NoProfile"), ps_quote("-ExecutionPolicy"), ps_quote("Bypass"),
            ps_quote("-File"), arg(script), ps_quote("-Package"), arg(info["path"]),
            ps_quote("-ExpectedSha256"), ps_quote(info["sha256"]),
            ps_quote("-ResultPath"), arg(result_path)]
    command = """
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$p = Start-Process -FilePath 'powershell.exe' -ArgumentList @(%s) -Verb RunAs -WindowStyle Hidden -Wait -PassThru
exit $p.ExitCode
""" % ",".join(args)
    emit("progress", {"message": "请在 Windows UAC 中允许 VB-CABLE 安装，完成后可能需要重启。", "fraction": .4})
    try:
        powershell(command, timeout=180)
    except Exception:
        if not result_path.exists():
            raise RuntimeError("驱动部署未完成。可能取消了 UAC，请再次点击安装。") from None
    result = json.loads(result_path.read_text("utf-8-sig"))
    if result.get("state") == "error":
        raise RuntimeError(result.get("error", "声卡安装失败。"))
    if result.get("state") == "reboot_required":
        write_json(data_dir()/"route-invalidated.json", {"reason": "driver_changed"})
    return {**info, **result}
