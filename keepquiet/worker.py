"""Spawn-safe process entry; bounded IPC contains metrics, never raw microphone PCM."""
from __future__ import annotations
import queue
import time
import numpy as np

from .audio import Bridge
from .benchmark import run_benchmark
from .devices import Route, stream_settings
from .dsp import load_models, enroll_pcm, read_wav
from .priority import audio_priority
from .storage import save_voiceprint, load_voiceprint, read_json, data_dir


def worker_entry(mode, config, conn):
    def emit(kind, value=None):
        try:
            conn.send({'kind': kind, 'value': value})
        except Exception:
            pass

    def cancelled():
        try:
            stopped = False
            while conn.poll():
                stopped |= conn.recv().get('command') == 'stop'
            return stopped
        except Exception:
            return True

    try:
        if mode in ('driver_check', 'driver_install'):
            from .driver import check_update, install_driver
            if mode == 'driver_check':
                result = check_update()
            else:
                result = install_driver(online=config.get('online', True), emit=emit)
            emit('driver', result)
            return

        if mode == 'prepare':
            emit('progress', {'message': '正在获取并校验本地模型…', 'fraction': 0})
            load_models(enrollment=True, download=True)
            emit('ready', {})
            return

        raw_battle = mode in ('run', 'benchmark') and bool(config.get('battle_mode', False))
        models = None if raw_battle else load_models(enrollment=(mode == 'enroll'))

        if mode == 'enroll':
            if config.get('wav'):
                pcm, rate = read_wav(config['wav'])
            else:
                import sounddevice as sd
                device = config['input_id']
                rate = int(sd.query_devices(device)['default_samplerate'])
                route = Route(device, device, rate=rate)
                pieces = []
                step = max(1, rate // 10)
                for remaining in (3, 2, 1):
                    if cancelled():
                        raise InterruptedError('录入已取消。')
                    emit('progress', {'message': f'准备朗读，{remaining} 秒后开始…', 'fraction': 0})
                    time.sleep(1)

                # P1-6: Async queue + InputStream callback to prevent spurious overflow failure
                pcm_queue = queue.Queue(maxsize=64)
                def _enroll_in_cb(indata, frames, ctime, status):
                    try:
                        pcm_queue.put_nowait(indata[:, 0].copy())
                    except queue.Full:
                        pass

                with sd.InputStream(
                    device=device, samplerate=rate, channels=1, blocksize=step,
                    dtype='float32', latency='low', extra_settings=stream_settings(route, device),
                    callback=_enroll_in_cb,
                ):
                    for i in range(60):
                        if cancelled():
                            raise InterruptedError('录入已取消。')
                        try:
                            part = pcm_queue.get(timeout=1.0)
                        except queue.Empty:
                            raise RuntimeError('录音设备未响应，录音中断。')
                        pieces.append(part)
                        emit('progress', {'message': f'请持续说话，还剩 {(59 - i) / 10:.1f} 秒', 'fraction': (i + 1) / 60})
                pcm = np.concatenate(pieces)

            voice, quality = enroll_pcm(pcm, rate, models)
            if cancelled():
                raise InterruptedError('录入已取消。')
            save_voiceprint(voice.to_json())
            pcm.fill(0)
            emit('enrolled', quality)
            return

        with audio_priority() as priority:
            emit('priority', priority)
            try:
                voice = None if raw_battle else load_voiceprint()
            except FileNotFoundError:
                voice = None
            except RuntimeError:
                if mode != 'benchmark':
                    raise
                voice = None
            a, b = config['input_id'], config['output_id']
            settings = read_json(data_dir() / 'settings.json') or {}
            gate_config = config.get('gate', {
                'threshold_db': settings.get('gate_threshold_db', -60.0),
                'purity': settings.get('filter_mode', settings.get('purity_mode', 'balanced')),
            })
            output_gain_db = config.get('output_gain_db', settings.get('output_gain_db', 0.0))
            if mode == 'benchmark':
                run_benchmark(a, b, models, voice, seconds=config.get('seconds', 2.5), emit=emit, cancelled=cancelled,
                              gate_config=gate_config, output_gain_db=output_gain_db, battle_mode=raw_battle)
                return

            # A mode-only restart reuses this run's route. A fresh Start always measures.
            if config.get('resume_route') is not None:
                route = Route(**config['resume_route'])
                if route.input_id != a or route.output_id != b:
                    raise RuntimeError('设备已变化，请点击开始运行重新测速。')
            else:
                route, _ = run_benchmark(a, b, models, voice, emit=emit, cancelled=cancelled,
                                         gate_config=gate_config, output_gain_db=output_gain_db,
                                         **({'battle_mode': True} if raw_battle else {}))

            if cancelled():
                message = '模式切换已取消。' if config.get('resume_route') is not None else '测速已取消。'
                raise InterruptedError(message)

            with Bridge(route, models, voice, gate_config=gate_config, output_gain_db=output_gain_db,
                        battle_mode=config.get('battle_mode', False)) as bridge:
                metering = bool(config.get('metering', False))
                bridge.set_metering(metering)
                muted = bool(config.get('muted', False))
                if muted:
                    bridge.set_muted(True)
                emit('running', {'route': route.to_dict(), 'muted': muted})
                if config.get('monitor', False):
                    enabled = bridge.set_monitor(True)
                    emit('monitor', {'enabled': enabled, 'error': bridge.monitor_error})
                now = time.perf_counter()
                next_stats = now + 0.5
                next_levels = now + 0.03333333333333333
                last_faults = 0
                fault_window_count = 0

                while True:
                    while conn.poll():
                        cmd = conn.recv()
                        c = cmd.get('command')
                        if c == 'stop':
                            return
                        elif c == 'mute':
                            bridge.set_muted(cmd['value'])
                        elif c == 'metering':
                            metering = bool(cmd['value'])
                            bridge.set_metering(metering)
                            next_levels = time.perf_counter() + 0.03333333333333333
                        elif c == 'gate':
                            if (isinstance(cmd['value'], dict) and
                                    cmd['value'].get('purity', gate_config.get('purity', 'balanced')) !=
                                    gate_config.get('purity', 'balanced')):
                                raise RuntimeError('滤波方式已改变，请通过界面切换模式。')
                            bridge.configure_gate(cmd['value'])
                            emit('gate', bridge.gate_status())
                        elif c == 'output_gain':
                            bridge.configure_output_gain(cmd['value'])
                        elif c == 'battle_mode':
                            if bool(cmd['value']) != raw_battle:
                                raise RuntimeError('模式已改变，请通过界面切换模式。')
                        elif c == 'monitor':
                            enabled = bridge.set_monitor(bool(cmd['value']))
                            emit('monitor', {'enabled': enabled, 'error': bridge.monitor_error})

                    bridge.tick()
                    now = time.perf_counter()
                    if metering and now >= next_levels:
                        emit('levels', {**bridge.take_levels(), 'gate': bridge.gate_status(), 'at': now})
                        next_levels = now + 0.03333333333333333

                    if now >= next_stats:
                        stats = bridge.stats()
                        emit('stats', stats)
                        faults = sum(stats.get(k, 0) for k in ('host_xruns', 'input_drops', 'output_underruns', 'output_drops'))
                        delta_faults = faults - last_faults
                        last_faults = faults
                        # P1-5: Graduated self-healing
                        if now - bridge._started > 3:
                            if delta_faults >= 20:
                                raise RuntimeError('音频流出现严重丢帧，输出已静音。请重新测速选择稳定方案。')
                            elif delta_faults >= 3:
                                fault_window_count += 1
                                if fault_window_count >= 3:
                                    raise RuntimeError('当前路线连续出现音频丢帧，输出已静音。请重新测速选择稳定方案。')
                                else:
                                    bridge.ring.clear()
                            else:
                                fault_window_count = 0
                        next_stats = now + 0.5
    except (BrokenPipeError, EOFError):
        pass
    except InterruptedError as error:
        emit('cancelled', str(error))
    except Exception as error:
        if mode == 'run':
            import sounddevice as sd
            if isinstance(error, sd.PortAudioError) or any(message in str(error) for message in
                    ('音频设备已断开', '麦克风没有返回音频')):
                emit('device_lost', str(error))
        emit('error', str(error))
    finally:
        try:
            emit('finished', {})
            conn.close()
        except Exception:
            pass

