"""Bounded capture/DSP/render bridge. Qt never runs in this process.

The prototype uses Python callbacks; the model and rate conversion execute in
Rust with the GIL released. This is soft real time, not a hard RT guarantee.
"""
from __future__ import annotations
from collections import deque
import math
import queue
import threading
import time
import numpy as np

from .devices import stream_settings
from .dsp import processor
from .gate import AudioGate
from .gain import OutputGain
from .battle import BattleEffect


def percentile(values, q=95):
    return float(np.percentile(values, q)) if len(values) else 0.0


class AudioRing:
    def __init__(self, rate: int, block_frames: int):
        self.rate = rate
        hop_frames = max(block_frames, int(rate * 0.016))
        self.target = max(block_frames * 2, hop_frames * 2, int(rate * 0.032))
        self.capacity = self.target + max(block_frames * 8, int(rate * 0.128))
        self.data = np.zeros(self.capacity, dtype=np.float32)
        self.read_pos = self.write_pos = self.size = 0
        self.lock = threading.Lock()
        self.primed = False
        self.underflows = self.drops = self.contentions = 0
        self.drift = 0.0
        self.correction = 0.0
        self._last_sample = 0.0
        self._idx = np.arange(self.capacity, dtype=np.intp)
        self._fp = np.arange(self.capacity, dtype=np.float32)

    def clear(self):
        with self.lock:
            self.read_pos = self.write_pos = self.size = 0
            self.primed = False
            self.drift = self.correction = 0.0
            self._last_sample = 0.0

    def push(self, pcm):
        n = len(pcm)
        if not n:
            return
        with self.lock:
            if n > self.capacity:
                pcm, n = pcm[-self.capacity:], self.capacity
            excess = max(0, self.size + n - self.capacity)
            if excess:
                self.read_pos = (self.read_pos + excess) % self.capacity
                self.size -= excess
                self.drops += 1
            first = min(n, self.capacity - self.write_pos)
            self.data[self.write_pos:self.write_pos + first] = pcm[:first]
            if first < n:
                self.data[:n - first] = pcm[first:]
            self.write_pos = (self.write_pos + n) % self.capacity
            self.size += n

    def pull_into(self, out):
        n = len(out)
        out.fill(0)
        if not self.lock.acquire(blocking=False):
            self.contentions += 1
            return
        try:
            if not self.primed:
                if self.size < max(self.target, n):
                    return
                self.primed = True
            error = (self.size - self.target - n / 2) / max(self.rate, 1)
            self.correction = 0.995 * self.correction + 0.005 * max(-0.0015, min(0.0015, error * 0.02))
            self.drift += n * self.correction
            adjust = max(-1, min(1, int(self.drift)))
            count = n + adjust
            if adjust > 0 and self.size < count:
                adjust = 0
                count = n
            if self.size < count:
                self.underflows += 1
                avail = self.size
                if avail > 0:
                    first = min(avail, self.capacity - self.read_pos)
                    out[:first] = self.data[self.read_pos:self.read_pos + first]
                    if first < avail:
                        out[first:avail] = self.data[:avail - first]
                    self.read_pos = (self.read_pos + avail) % self.capacity
                    self.size = 0
                    last = float(out[avail - 1])
                    rem = n - avail
                    if rem > 0 and last != 0.0:
                        out[avail:] = last * np.linspace(0.9, 0.0, rem, dtype=np.float32)
                self._last_sample = 0.0
                self.primed = False
                return
            if adjust:
                indexes = (self.read_pos + self._idx[:count]) % self.capacity
                x = self.data[indexes]
                out[:] = np.interp(np.linspace(0, count - 1, n), self._fp[:count], x)
                self.drift -= adjust
            else:
                first = min(n, self.capacity - self.read_pos)
                out[:first] = self.data[self.read_pos:self.read_pos + first]
                if first < n:
                    out[first:] = self.data[:n - first]
            self.read_pos = (self.read_pos + count) % self.capacity
            self.size -= count
            if n > 0:
                self._last_sample = float(out[-1])
        finally:
            self.lock.release()



class Bridge:
    def __init__(self, route, models, voiceprint, *, probe=False, gate_config=None, output_gain_db=0.0, battle_mode=False):
        import alkove
        self.route = route
        self.processor = None if battle_mode else processor(models, voiceprint, rate=route.rate)
        self.gate = AudioGate(**(gate_config or {}))
        self.output_gain = OutputGain(output_gain_db, rate=route.rate)
        self.battle_mode = bool(battle_mode)
        self.battle_effect = BattleEffect(route.rate)
        self.resampler = alkove.Resampler(16000, route.rate) if route.rate != 16000 and not battle_mode else None
        self.input = self.output = None
        self.ring = AudioRing(route.rate, route.frames)
        self.capture = queue.Queue(maxsize=16)
        self.probe = probe
        self.muted = False
        self.fault = None
        self.input_drops = self.host_xruns = self.deadlines = 0
        self.callbacks = 0
        self.input_level = self.output_level = 0.0
        self._hop_in_rms = 0.0
        self._metering = False
        self._meter_energy = [0.0, 0.0]
        self._meter_samples = [0, 0]
        self.processing = deque(maxlen=2048)
        self.waits = deque(maxlen=2048)
        self.depths = deque(maxlen=2048)
        self.intervals = deque(maxlen=2048)
        self._last_callback = None
        self._started = 0.0
        self._mono_out = np.zeros(route.frames * 8, dtype=np.float32)

        # P2-7: Headphone monitor
        self.monitor_enabled = False
        self.monitor_error = None
        self.monitor_output = None
        self.monitor_ring = None
        self._monitor_mono = np.zeros(route.frames * 8, dtype=np.float32)

    def __enter__(self):
        import sounddevice as sd
        r = self.route
        out_channels = min(2, sd.query_devices(r.output_id)['max_output_channels'])
        try:
            self.input = sd.InputStream(
                device=r.input_id, samplerate=r.rate, blocksize=r.frames,
                channels=1, dtype='float32', latency='low', callback=self._in_callback,
                extra_settings=stream_settings(r, r.input_id),
            )
            self.output = sd.OutputStream(
                device=r.output_id, samplerate=r.rate, blocksize=r.frames,
                channels=out_channels, dtype='float32', latency='low', callback=self._out_callback,
                extra_settings=stream_settings(r, r.output_id),
            )
            self._started = time.perf_counter()
            self.input.start()
            self.output.start()
            return self
        except BaseException:
            self.close()
            raise

    def set_monitor(self, enabled: bool):
        import sounddevice as sd
        self.monitor_error = None
        if self.monitor_enabled == enabled:
            return self.monitor_enabled
        if enabled:
            try:
                default_dev = sd.default.device[1]
                devs = sd.query_devices()
                def physical(index):
                    if index is None or index < 0 or index == self.route.output_id:
                        return False
                    dev = devs[index]
                    name = dev['name'].lower()
                    return dev['max_output_channels'] > 0 and not any(
                        token in name for token in ('cable', 'vb-audio', 'voicemeeter'))
                if not physical(default_dev):
                    default_dev = next(
                        i for i, d in enumerate(devs)
                        if physical(i)
                    )
                channels = min(2, sd.query_devices(default_dev)['max_output_channels'])
                self.monitor_ring = AudioRing(self.route.rate, self.route.frames)
                def _mon_out_cb(outdata, frames, ctime, status):
                    if frames > len(self._monitor_mono):
                        outdata.fill(0)
                        return
                    mono = self._monitor_mono[:frames]
                    self.monitor_ring.pull_into(mono)
                    outdata[:] = mono[:, None]
                self.monitor_output = sd.OutputStream(
                    device=default_dev, samplerate=self.route.rate, blocksize=self.route.frames,
                    channels=channels, dtype='float32', latency='low', callback=_mon_out_cb,
                )
                self.monitor_output.start()
                self.monitor_enabled = True
            except Exception as error:
                self.monitor_error = str(error) or "未找到可用的物理播放设备。"
                self.monitor_enabled = False
                if self.monitor_output is not None:
                    try:
                        self.monitor_output.close()
                    except Exception:
                        pass
                    self.monitor_output = None
                self.monitor_ring = None
        else:
            self.monitor_enabled = False
            if self.monitor_output is not None:
                try:
                    self.monitor_output.stop()
                    self.monitor_output.close()
                except Exception:
                    pass
                self.monitor_output = None
            self.monitor_ring = None
        return self.monitor_enabled

    def tick(self, timeout=0.25):
        if self.fault:
            raise RuntimeError(self.fault)
        if not (self.input.active and self.output.active):
            raise RuntimeError('音频设备已断开或流已停止，输出已静音。')
        try:
            x, captured = self.capture.get(timeout=timeout)
        except queue.Empty:
            if time.perf_counter() - self._started > 2:
                raise RuntimeError('麦克风没有返回音频，请检查设备和麦克风权限。')
            return
        start = time.perf_counter()
        self.waits.append((start - captured) * 1000)
        self.input_level = math.sqrt(float(np.dot(x, x)) / len(x) + 1e-12)
        if self.input_level > self._hop_in_rms:
            self._hop_in_rms = self.input_level
        if self._metering:
            self._meter_energy[0] += (self.input_level ** 2) * len(x)
            self._meter_samples[0] += len(x)
        if self.battle_mode:
            y = self.battle_effect.process(x)
        else:
            y = self.processor.push(x).audio
        if len(y):
            if not np.isfinite(y).all():
                self.fault = '音频处理返回异常采样，输出已静音。'
                raise RuntimeError(self.fault)
            hop_in_rms = self._hop_in_rms if self._hop_in_rms > 0.0 else self.input_level
            self._hop_in_rms = self.input_level * 0.5
            if not self.battle_mode:
                y = self.gate.process(y, in_rms=hop_in_rms)

            if not self.battle_mode and self.resampler is not None:
                y = self.resampler.push(y)
            if len(y):
                if not self.battle_mode:
                    y = self.output_gain.process(y)
                self.output_level = math.sqrt(float(np.dot(y, y)) / len(y) + 1e-12)
                if self._metering:
                    self._meter_energy[1] += (self.output_level ** 2) * len(y)
                    self._meter_samples[1] += len(y)
                np.clip(y, -0.98, 0.98, out=y)
                self.ring.push(y)
                # P2-7: Feed monitor ring buffer
                if self.monitor_enabled and self.monitor_ring is not None:
                    self.monitor_ring.push(y)

        duration = (time.perf_counter() - start) * 1000
        self.processing.append(duration)
        self.depths.append(self.ring.size / self.route.rate * 1000)
        if duration > self.route.block_ms:
            self.deadlines += 1

    def close(self):
        if self.monitor_output is not None:
            try:
                self.monitor_output.stop()
                self.monitor_output.close()
            except Exception:
                pass
            self.monitor_output = None
        if self.input is not None:
            try:
                self.input.stop()
                self.input.close()
            except Exception:
                pass
            self.input = None
        if self.output is not None:
            try:
                self.output.stop()
                self.output.close()
            except Exception:
                pass
            self.output = None

    def configure_gate(self, value):
        if isinstance(value, dict):
            self.gate.configure(**value)
        else:
            self.gate.configure(threshold_db=float(value))

    def gate_status(self):
        return self.gate.status()

    def configure_output_gain(self, value):
        self.output_gain.configure(float(value))

    def _in_callback(self, data, frames, timing, status):
        now = time.perf_counter()
        if self._last_callback is not None:
            self.intervals.append((now - self._last_callback) * 1000)
        self._last_callback = now
        self.callbacks += 1
        if status:
            self.host_xruns += 1
        try:
            self.capture.put_nowait((data[:, 0].copy(), now))
        except queue.Full:
            self.input_drops += 1

    def _out_callback(self, data, frames, timing, status):
        if status:
            self.host_xruns += 1
        if frames > len(self._mono_out):
            data.fill(0)
            return
        mono = self._mono_out[:frames]
        self.ring.pull_into(mono)
        if self.probe or self.muted or self.fault:
            data.fill(0)
        else:
            data[:] = mono[:, None]

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def set_muted(self, value):
        self.muted = bool(value)
        self.ring.clear()

    def set_purity(self, purity: str):
        self.gate.configure(purity=purity)

    def set_metering(self, enabled):
        self._metering = bool(enabled)
        if not self._metering:
            self.input_level = self.output_level = 0.0
            self._meter_energy = [0.0, 0.0]
            self._meter_samples = [0, 0]

    def take_levels(self):
        values = []
        for i in range(2):
            count = self._meter_samples[i]
            if count:
                energy = self._meter_energy[i]
                self._meter_energy[i] = 0.0
                self._meter_samples[i] = 0
                rms = math.sqrt(energy / count)
            else:
                rms = 0.0
            values.append(rms)
        self.input_level, self.output_level = values
        if self.muted or self.probe:
            self.output_level = 0.0
        return {'input_level': self.input_level, 'output_level': self.output_level}

    def reset_metrics(self):
        self.processing.clear()
        self.waits.clear()
        self.depths.clear()
        self.intervals.clear()
        self.ring.underflows = self.ring.drops = self.ring.contentions = 0
        self.host_xruns = self.input_drops = self.deadlines = 0

    def stats(self):
        input_ms = float(getattr(self.input, 'latency', self.route.block_ms / 1000)) * 1000
        output_ms = float(getattr(self.output, 'latency', self.route.block_ms / 1000)) * 1000
        dsp_p50_ms = percentile(self.processing, 50)
        dsp_ms = percentile(self.processing, 95)
        dsp_p99_ms = percentile(self.processing, 99)
        wait_ms = percentile(self.waits, 95)
        queue_ms = percentile(self.depths, 95)
        model_ms = 0 if self.battle_mode else 16
        estimate = input_ms + output_ms + model_ms + dsp_ms + wait_ms + queue_ms
        if self.resampler and not self.battle_mode:
            estimate += 4
        return {
            'input_ms': input_ms,
            'output_ms': output_ms,
            'model_ms': model_ms,
            'dsp_p50_ms': dsp_p50_ms,
            'dsp_p95_ms': dsp_ms,
            'dsp_p99_ms': dsp_p99_ms,
            'wait_p95_ms': wait_ms,
            'queue_p95_ms': queue_ms,
            'estimated_local_ms': estimate,
            'callback_p99_ms': percentile(self.intervals, 99),
            'host_xruns': self.host_xruns,
            'input_drops': self.input_drops,
            'output_underruns': self.ring.underflows,
            'output_drops': self.ring.drops,
            'callback_contentions': self.ring.contentions,
            'deadline_misses': self.deadlines,
            'callbacks': self.callbacks,
            'processed_blocks': len(self.processing),
            'input_level': self.input_level,
            'output_level': self.output_level,
            'gate': self.gate.status(),
            'output_gain_db': self.output_gain.gain_db,
        }

