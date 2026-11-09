from __future__ import annotations
import argparse
import json
import multiprocessing as mp
from pathlib import Path
import sys


def main():
    mp.freeze_support()
    parser = argparse.ArgumentParser(description="KeepQuiet Windows target-speaker microphone bridge")
    parser.add_argument("--log", type=Path, help="将 CLI 输出写入文件（Windows GUI 发布版诊断）")
    sub = parser.add_subparsers(dest="command")
    ui = sub.add_parser("ui", help="打开原生控制面板")
    ui.add_argument("--screenshot", type=Path)
    sub.add_parser("devices", help="枚举音频设备")
    sub.add_parser("prepare", help="获取并校验模型")
    driver = sub.add_parser("driver", help="检测、校验或自动部署 VB-CABLE")
    driver.add_argument("--install", action="store_true")
    driver.add_argument("--offline", action="store_true")
    enroll = sub.add_parser("enroll", help="从 PCM WAV 生成并加密目标声纹")
    enroll.add_argument("wav", type=Path)
    process = sub.add_parser("process", help="离线验证目标说话人提取")
    process.add_argument("wav", type=Path)
    process.add_argument("--reference", type=Path, required=True)
    process.add_argument("--out", type=Path, required=True)
    for name in ("benchmark", "run"):
        task = sub.add_parser(name)
        task.add_argument("--input", type=int, help="不填时自动选择物理麦克风")
        task.add_argument("--output", type=int, help="不填时自动选择虚拟声卡")
        if name == "benchmark":
            task.add_argument("--seconds", type=float, default=2.5)
    args = parser.parse_args()
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = args.log.open("w", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout
    try:
        if args.command in (None, "ui"):
            from .ui import main as ui_main
            return ui_main(getattr(args, "screenshot", None))
        if args.command == "devices":
            from .devices import devices
            print(json.dumps(devices(), ensure_ascii=False, indent=2))
        elif args.command == "prepare":
            from .dsp import load_models
            print(load_models(enrollment=True, download=True))
        elif args.command == "driver":
            from .driver import check_update, install_driver
            result = install_driver(not args.offline) if args.install else check_update(not args.offline)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "enroll":
            from .dsp import read_wav, enroll_pcm
            from .storage import save_voiceprint
            x, rate = read_wav(args.wav)
            voice, quality = enroll_pcm(x, rate)
            save_voiceprint(voice.to_json())
            print(json.dumps(quality, indent=2))
        elif args.command == "process":
            import numpy as np
            from .dsp import read_wav, write_wav, enroll_pcm, load_models, processor
            models = load_models(enrollment=True)
            reference, rate = read_wav(args.reference)
            voice, _ = enroll_pcm(reference, rate, models)
            x, rate = read_wav(args.wav)
            p = processor(models, voice, rate)
            parts = [p.push(x[i:i+rate//125]).audio for i in range(0, len(x), rate//125)]
            parts.append(p.end().audio)
            y = np.concatenate(parts)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_wav(args.out, y)
            print(json.dumps({"input_s": len(x)/rate, "output_s": len(y)/16000, "out": str(args.out)}))
        else:
            from .worker import worker_entry
            if args.input is None or args.output is None:
                from .devices import devices, default_pair
                a, b = default_pair(devices())
                if args.input is None:
                    if not a:
                        raise RuntimeError("没有找到物理麦克风。")
                    args.input = a["id"]
                if args.output is None:
                    if not b:
                        raise RuntimeError("没有找到虚拟声卡，请先自动部署 VB-CABLE。")
                    args.output = b["id"]
            parent, child = mp.get_context("spawn").Pipe()
            proc = mp.get_context("spawn").Process(target=worker_entry,
                args=(args.command, {"input_id": args.input, "output_id": args.output,
                                     "seconds": getattr(args, "seconds", 2.5)}, child))
            proc.start()
            child.close()
            failed = False
            try:
                while True:
                    try:
                        if parent.poll(.2):
                            event = parent.recv()
                            print(json.dumps(event, ensure_ascii=False), flush=True)
                            failed |= event["kind"] == "error"
                            if event["kind"] == "finished":
                                break
                        elif not proc.is_alive():
                            break
                    except (EOFError, OSError):
                        break
            except KeyboardInterrupt:
                parent.send({"command": "stop"})
            finally:
                proc.join(timeout=3)
                if proc.is_alive():
                    proc.terminate()
                parent.close()
            return 1 if failed else 0
        return 0
    except Exception as error:
        print(f"KeepQuiet: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
