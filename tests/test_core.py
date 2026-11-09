import json
import os
from pathlib import Path
import numpy as np
import pytest

from keepquiet.audio import AudioRing
from keepquiet.benchmark import select_best, stable
from keepquiet.driver import package_url, stage_package, BUNDLED_SHA256
from keepquiet.dsp import enrollment_quality, processor
from keepquiet.storage import atomic_bytes, protect, save_voiceprint, load_voiceprint, data_dir


def test_ring_order_and_bounded_overflow():
    ring = AudioRing(1000, 16)
    ring.push(np.arange(32, dtype=np.float32))
    out = np.empty(16, np.float32)
    ring.pull_into(out)
    np.testing.assert_array_equal(out, np.arange(16))
    ring.push(np.arange(1000, dtype=np.float32))
    assert ring.size <= ring.capacity and ring.drops == 1


def test_ring_underflow_and_callback_contention_are_silent():
    ring = AudioRing(16000, 128)
    out = np.ones(128, np.float32)
    ring.pull_into(out)
    assert not out.any() and ring.underflows == 0  # normal pre-roll
    ring.push(np.ones(512, np.float32))
    ring.lock.acquire()
    try:
        ring.pull_into(out)
    finally:
        ring.lock.release()
    assert not out.any() and ring.contentions == 1
    for _ in range(8):
        ring.pull_into(out)
    assert ring.underflows >= 1 and not out.any()


def test_ring_long_clock_drift_stays_bounded():
    ring = AudioRing(16000, 256)
    out = np.empty(256, np.float32)
    for i in range(2000):
        ring.push(np.ones(257 if i % 5 == 0 else 256, np.float32))
        ring.pull_into(out)
    assert ring.size < ring.capacity
    assert abs(ring.correction) <= .0015
    assert np.isfinite(out).all()


def test_ring_contiguous_and_wrapped_reads_preserve_sample_order():
    ring = AudioRing(16000, 127)
    ring.push(np.arange(635, dtype=np.float32))
    out = np.empty(127, np.float32)
    for step in range(40):
        ring.pull_into(out)
        np.testing.assert_array_equal(out, np.arange(step*127, (step+1)*127, dtype=np.float32))
        start = 635+step*127
        ring.push(np.arange(start, start+127, dtype=np.float32))


def test_enrollment_rejects_silence_clipping_and_short_audio():
    with pytest.raises(ValueError, match="至少"):
        enrollment_quality(np.ones(1000), 16000)
    with pytest.raises(ValueError, match="有效声音"):
        enrollment_quality(np.zeros(64000), 16000)
    with pytest.raises(ValueError, match="削波"):
        enrollment_quality(np.ones(64000), 16000)
    with pytest.raises(ValueError, match="无效"):
        enrollment_quality(np.full(64000, np.nan), 16000)


def test_missing_voice_never_enables_passthrough():
    with pytest.raises(ValueError, match="禁止"):
        processor(None, None)


def stats(**changes):
    return {"processed_blocks": 100, "host_xruns": 0, "input_drops": 0,
            "output_underruns": 0, "output_drops": 0, "callback_contentions": 0,
            "deadline_misses": 0, "dsp_p99_ms": 1, "callback_p99_ms": 8,
            "estimated_local_ms": 45, **changes}


def test_benchmark_rejects_fast_unstable_and_no_eligible_route():
    a = {"stable": stable(stats(host_xruns=1), 8), "stats": stats(estimated_local_ms=20), "route": {"exclusive": False}}
    b = {"stable": stable(stats(), 8), "stats": stats(), "route": {"exclusive": False}}
    assert select_best([a, b]) is b
    assert select_best([a]) is None
    assert not stable(stats(dsp_p99_ms=7), 8)
    assert not stable(stats(callback_p99_ms=50), 8)


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_dpapi_roundtrip_and_tamper_rejection():
    secret = b'{"embedding":[0.1,0.2]}'
    encrypted = protect(secret)
    assert secret not in encrypted
    assert protect(encrypted, decrypt=True) == secret
    with pytest.raises(OSError):
        protect(encrypted[:-4] + b"xxxx", decrypt=True)


def test_atomic_replace_no_temporary_file_left(tmp_path):
    path = tmp_path / "profile"
    atomic_bytes(path, b"one")
    atomic_bytes(path, b"two")
    assert path.read_bytes() == b"two"
    assert list(tmp_path.iterdir()) == [path]


def test_driver_only_constructs_official_package_urls():
    assert package_url("VBCABLE_Driver_Pack45.zip").startswith("https://download.vb-audio.com/")
    for bad in ("../evil.zip", "https://example.com/x.zip", "foo.exe", "VBCABLE_A_B.zip"):
        with pytest.raises(ValueError):
            package_url(bad)


def test_bundled_driver_hash_and_inf_version(tmp_path, monkeypatch):
    monkeypatch.setenv("KEEPQUIET_DATA_DIR", str(tmp_path))
    path, digest, version = stage_package()
    assert path.exists() and digest == BUNDLED_SHA256 and version == "3.3.1.7"
