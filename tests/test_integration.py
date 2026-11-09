"""Actual vendor models and public vendor fixtures, no user's microphone needed."""
from pathlib import Path
import numpy as np
import pytest
import alkove

from keepquiet.dsp import load_models, read_wav, enroll_pcm, processor
from keepquiet.storage import save_voiceprint, load_voiceprint, data_dir

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def models():
    return load_models(enrollment=True)


@pytest.fixture(scope="module")
def voice(models):
    x, rate = read_wav(FIX / "enroll.wav")
    return enroll_pcm(x, rate, models)[0]


@pytest.mark.integration
def test_model_streaming_equals_whole_file_and_has_correct_duration(models, voice):
    x, rate = read_wav(FIX / "mix.wav")
    whole = processor(models, voice, rate)
    a = np.concatenate([whole.push(x).audio, whole.end().audio])
    stream = processor(models, voice, rate)
    parts = [stream.push(x[i:i+128]).audio for i in range(0, len(x), 128)]
    parts.append(stream.end().audio)
    b = np.concatenate(parts)
    assert len(a) == len(b) == round(len(x)*16000/rate)
    np.testing.assert_allclose(a, b, atol=2e-5, rtol=1e-4)
    assert np.isfinite(b).all() and np.max(np.abs(b)) > .001


@pytest.mark.integration
def test_matching_voiceprint_is_recognized(models, voice):
    speech, rate = read_wav(FIX / "speech.wav")
    if rate != 16000:
        speech = alkove.resample(speech, rate, 16000)
    other = alkove.Timbre(models).embed(speech[8000:72000])
    same, score = alkove.Timbre.verify(voice, other)
    assert same and score > 0


@pytest.mark.integration
def test_saved_voiceprint_loads_without_plaintext(tmp_path, monkeypatch, voice):
    monkeypatch.setenv("KEEPQUIET_DATA_DIR", str(tmp_path))
    save_voiceprint(voice.to_json())
    loaded = load_voiceprint()
    np.testing.assert_array_equal(loaded.embedding, voice.embedding)
    data = (data_dir()/"voiceprint.protected").read_bytes()
    assert b"centers" not in data and b"embedding" not in data


@pytest.mark.integration
def test_native_model_is_below_realtime_on_this_machine(models, voice):
    # Functional real-time sanity check; detailed timings belong in the report.
    import time
    x, rate = read_wav(FIX / "mix.wav")
    p = processor(models, voice, rate)
    start = time.perf_counter()
    p.push(x)
    p.end()
    assert time.perf_counter() - start < len(x)/rate
