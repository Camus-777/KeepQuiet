from types import SimpleNamespace

import numpy as np
import pytest

from keepquiet.dsp import enroll_pcm


@pytest.mark.parametrize('consistent', [True, False])
def test_enrollment_rejects_a_changed_speaker_before_returning_a_profile(monkeypatch, consistent):
    import alkove
    monkeypatch.setattr(alkove, 'process', lambda *a, **kw: SimpleNamespace(
        speech=[SimpleNamespace(start=0., end=4.)]))
    class Timbre:
        def __init__(self, models): pass
        def embed(self, pcm, **kwargs): return 'profile'
        def verify(self, a, b, **kwargs): return consistent, .8 if consistent else .1
    monkeypatch.setattr(alkove, 'Timbre', Timbre)
    monkeypatch.setattr(alkove, 'Voiceprint', SimpleNamespace(merge=lambda prints: 'profile'))
    pcm = np.sin(np.arange(64000)*.1).astype(np.float32)*.1
    if consistent:
        voice, quality = enroll_pcm(pcm, 16000, object())
        assert voice == 'profile' and quality['speaker_consistency_score'] == .8
    else:
        with pytest.raises(ValueError, match='声线不一致'):
            enroll_pcm(pcm, 16000, object())


def test_enrollment_requires_enough_actual_speech(monkeypatch):
    import alkove
    monkeypatch.setattr(alkove, 'process', lambda *a, **kw: SimpleNamespace(
        speech=[SimpleNamespace(start=0., end=2.)]))
    pcm = np.sin(np.arange(64000)*.1).astype(np.float32)*.1
    with pytest.raises(ValueError, match='不足 3 秒'):
        enroll_pcm(pcm, 16000, object())
