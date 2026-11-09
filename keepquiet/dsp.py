"""Voice extraction has no passthrough mode. Missing/failed model means silence."""
from __future__ import annotations
import sys
from pathlib import Path
import wave
import numpy as np


def model_dir():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    path = root / "models"
    return path if (path / "alkove-focus-1-preview.alk").exists() else None


def load_models(enrollment=False, download=False):
    import alkove
    # Alkove 0.4.0 validates Cue even with cue=False. Keep the vendor API intact.
    names = ["focus", "cue", "timbre"] if enrollment else ["focus", "cue"]
    return alkove.Models.load(names, dir=model_dir(), download=download)


def processor(models, voiceprint, rate: int = 16000):
    import os
    import alkove
    if voiceprint is None:
        raise ValueError('目标声纹缺失，禁止输出原始麦克风声音。')
    try:
        strength = float(os.environ.get('KEEPQUIET_STRENGTH', '1.0'))
        strength = max(0.5, min(1.0, strength))
    except Exception:
        strength = 1.0
    proc = alkove.Processor(
        models, focus=True, voiceprint=voiceprint,
        strength=strength, cue=False, normalize=False, rate=rate,
    )
    return proc



def read_wav(path):
    with wave.open(str(path), "rb") as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        data = wav.readframes(wav.getnframes())
    if width not in (2, 4):
        raise ValueError("请使用 16 或 32 bit PCM WAV 文件。")
    pcm = np.frombuffer(data, dtype="<i2" if width == 2 else "<i4").astype(np.float32)
    pcm *= 1 / (32768 if width == 2 else 2147483648)
    return pcm.reshape(-1, channels).mean(axis=1), rate


def write_wav(path, pcm, rate=16000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())


def enrollment_quality(pcm, rate):
    x = np.asarray(pcm, dtype=np.float32)
    if not np.isfinite(x).all():
        raise ValueError("录音包含无效采样，请重新录入。")
    if len(x) < rate * 3:
        raise ValueError("需要至少 3 秒录音，建议安静环境连续说话 6 秒。")
    clipping = float(np.mean(np.abs(x) > .995))
    n = rate // 50
    rms = np.sqrt(np.mean(x[:len(x)//n*n].reshape(-1, n) ** 2, axis=1) + 1e-12)
    voiced = rms > max(.006, float(np.percentile(rms, 15)) * 2)
    # A loud, steady recording is still eligible (the model validates the voice).
    active_seconds = float(np.sum(rms > .006) * .02)
    if active_seconds < 1.8:
        raise ValueError("有效声音不足或麦克风太轻，请靠近麦克风再读一次。")
    if clipping > .01:
        raise ValueError("录音发生削波，请降低麦克风增益再读一次。")
    return {"duration_s": len(x) / rate, "active_s": active_seconds,
            "clipping_fraction": clipping, "dynamic_voiced_fraction": float(voiced.mean())}


def enroll_pcm(pcm, rate: int, models=None):
    import alkove
    from .dsp import enrollment_quality, load_models
    quality = enrollment_quality(pcm, rate)
    mono = alkove.resample(pcm, rate, 16000) if rate != 16000 else pcm
    model = models or load_models(enrollment=True)
    speech = alkove.process(model, mono, rate=16000, focus=False, cue=True)
    speech_seconds = sum(span.end - span.start for span in speech.speech)
    if speech_seconds < 3.0:
        raise ValueError('有效说话内容不足 3 秒，请在安静处完整朗读提示语。')
    quality['detected_speech_s'] = speech_seconds
    active = np.concatenate([
        mono[max(0, round(span.start * 16000)):min(len(mono), round(span.end * 16000))]
        for span in speech.speech
    ])
    timbre = alkove.Timbre(model)
    middle = len(active) // 2
    if middle < 24000:
        raise ValueError('有效说话内容不足 3 秒，请完整朗读提示语。')
    vp_first = timbre.embed(active[:middle], source='raw')
    vp_second = timbre.embed(active[middle:], source='raw')
    same, score = timbre.verify(vp_first, vp_second, level='lenient')
    if not same:
        raise ValueError('录音前后声线不一致，可能混入其他人声，请独自重新录入。')
    quality['speaker_consistency_score'] = score
    vp_active = timbre.embed(active, source='raw')
    vp_mono = timbre.embed(mono, source='raw')
    voice = alkove.Voiceprint.merge([vp_active, vp_first, vp_second, vp_mono])
    return voice, quality

