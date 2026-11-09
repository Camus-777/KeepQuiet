from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import json
import platform
import subprocess


def _endpoint_ids_registry():
    import sys
    if sys.platform != "win32":
        return None
    import winreg
    active_guids = set()
    for flow in ("Render", "Capture"):
        flow_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\{flow}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, flow_path) as fk:
                i = 0
                while True:
                    try:
                        guid = winreg.EnumKey(fk, i)
                        i += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(fk, guid) as gk:
                            state, _ = winreg.QueryValueEx(gk, "DeviceState")
                            if state == 1:
                                active_guids.add(guid.upper())
                    except OSError:
                        continue
        except OSError:
            return None
    rows = []
    enum_path = r"SYSTEM\CurrentControlSet\Enum\SWD\MMDEVAPI"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, enum_path) as root:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
                i += 1
            except OSError:
                break
            sub_up = sub.upper()
            if "." not in sub_up or sub_up.rsplit(".", 1)[1] not in active_guids:
                continue
            try:
                with winreg.OpenKey(root, sub) as k:
                    name, _ = winreg.QueryValueEx(k, "FriendlyName")
                    rows.append({"Name": name, "DeviceID": f"SWD\\MMDEVAPI\\{sub_up}"})
            except OSError:
                continue
    return rows


def endpoint_ids():
    """Windows endpoint identities survive PortAudio device-number changes."""
    try:
        rows = _endpoint_ids_registry()
        if rows:
            return rows
    except OSError:
        pass
    from .driver import powershell
    try:
        text = powershell("""
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
@(Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPClass -eq 'AudioEndpoint' } |
 Select-Object Name,DeviceID) | ConvertTo-Json -Compress
""", timeout=10)
        rows = json.loads(text or '[]')
        return rows if isinstance(rows, list) else [rows]
    except (RuntimeError, OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        return []


def selection_key(device):
    return {key: device[key] for key in ('name', 'host', 'endpoint_id') if device.get(key)}


def find_selection(items, saved):
    if not saved:
        return None
    if saved.get('endpoint_id'):
        matches = [d for d in items if d.get('endpoint_id') == saved['endpoint_id'] and d['host'] == saved['host']]
    else:
        matches = [d for d in items if d['name'] == saved.get('name') and d['host'] == saved.get('host')]
    # Missing or ambiguous endpoints require an explicit choice, never a substitute mic.
    return matches[0] if len(matches) == 1 else None


def devices(*, refresh=False) -> list[dict]:
    import sounddevice as sd
    if refresh:
        # Used only by the UI process, which owns no audio streams. Workers
        # retain their own independent PortAudio instances.
        sd._terminate()
        sd._initialize()
    hosts = sd.query_hostapis()
    result = []
    for i, d in enumerate(sd.query_devices()):
        host = hosts[d["hostapi"]]["name"]
        # Only expose WASAPI; legacy aliases duplicate the same physical devices.
        if host != "Windows WASAPI":
            continue
        result.append({"id": i, "name": d["name"], "host": host,
                       "inputs": d["max_input_channels"], "outputs": d["max_output_channels"],
                       "rate": int(d["default_samplerate"]),
                       "virtual": any(s in d["name"].lower() for s in
                                      ("cable", "voicemeeter", "keepquiet"))})
    endpoints = endpoint_ids()
    for d in result:
        if d['host'] != 'Windows WASAPI':
            continue
        prefix = '{0.0.1.' if d['inputs'] else '{0.0.0.'
        matches = [e['DeviceID'] for e in endpoints if e['Name'] == d['name'] and prefix in e['DeviceID']]
        if len(matches) == 1:
            d['endpoint_id'] = matches[0]
    return result


def default_pair(items: list[dict]):
    ins = [x for x in items if x["inputs"] and not x["virtual"]]
    outs = [x for x in items if x["outputs"] and x["virtual"]]
    order = lambda x: (x["host"] != "Windows WASAPI", x["id"])
    return (sorted(ins, key=order)[0] if ins else None,
            sorted(outs, key=order)[0] if outs else None)


@dataclass(frozen=True)
class Route:
    input_id: int
    output_id: int
    rate: int = 48000
    block_ms: int = 8
    exclusive: bool = False

    @property
    def frames(self):
        return self.rate * self.block_ms // 1000

    @property
    def label(self):
        return f"{'独占' if self.exclusive else '共享'} · {self.rate // 1000} kHz · {self.block_ms} ms"

    def to_dict(self):
        return asdict(self)


def candidates(input_id: int, output_id: int) -> list[Route]:
    items = {x["id"]: x for x in devices()}
    a, b = items[input_id], items[output_id]
    if a["host"] != b["host"]:
        raise ValueError("输入和输出请选择同一种音频接口（优先 Windows WASAPI）。")
    wasapi = a["host"] == "Windows WASAPI"
    modes = (False, True) if wasapi else (False,)
    rates = list(dict.fromkeys([a["rate"], 48000, 16000]))
    return [Route(input_id, output_id, rate, ms, exclusive)
            for exclusive in modes for rate in rates for ms in (8, 16, 32)]


def fingerprint(input_id: int, output_id: int) -> str:
    import alkove
    from .driver import installed_driver
    items = {x['id']: x for x in devices()}
    obj = {
        'machine': platform.node(),
        'os': platform.version(),
        'cpu': platform.processor(),
        'devices': [items[input_id], items[output_id]],
        'engine': alkove.__version__,
        'focus': alkove.MANIFEST['models']['focus']['sha256'],
        'audio_pipeline': 5,
        'schema': 3,
        'virtual_driver': installed_driver(),
    }
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()



def stream_settings(route: Route, device_id: int):
    import sounddevice as sd
    d = sd.query_devices(device_id)
    host = sd.query_hostapis(d["hostapi"])["name"]
    return sd.WasapiSettings(exclusive=route.exclusive, auto_convert=not route.exclusive) \
        if host == "Windows WASAPI" else None
