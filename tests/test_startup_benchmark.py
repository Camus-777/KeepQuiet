from contextlib import nullcontext
import pytest

from keepquiet.devices import Route
from test_profiles import make_window, close_window


@pytest.mark.parametrize('purity,battle', [('natural', False), ('balanced', False), ('ultra', False), ('balanced', True)])
def test_every_mode_start_measures_current_profile_before_running(monkeypatch, purity, battle):
    from keepquiet import worker
    measurements = []
    monkeypatch.setattr(worker, 'load_models', lambda **kw: {})
    monkeypatch.setattr(worker, 'load_voiceprint', lambda: object())
    monkeypatch.setattr(worker, 'read_json', lambda *a: {})
    monkeypatch.setattr(worker, 'audio_priority', lambda: nullcontext({}))
    def forbid_cache(*a, **kw):
        raise AssertionError('Each ordinary start must benchmark, even with an existing cache')
    monkeypatch.setattr(worker, 'cached_route', forbid_cache, raising=False)
    gate = {'purity': purity, 'threshold_db': -60}
    def benchmark(a, b, models, voice, **kw):
        assert kw['gate_config'] == gate
        assert kw['output_gain_db'] == 3
        assert kw.get('battle_mode', False) is battle
        measurements.append(purity)
        report = {'selected': {'route': Route(a, b).to_dict(), 'stats': {'estimated_local_ms': 80}}}
        kw['emit']('progress', {'stage': 'benchmark', 'message': 'measuring', 'fraction': .1})
        kw['emit']('benchmark', report)
        return Route(a, b), report
    monkeypatch.setattr(worker, 'run_benchmark', benchmark)
    class FakeBridge:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def set_metering(self, value): pass
    monkeypatch.setattr(worker, 'Bridge', FakeBridge)
    for _ in range(2):
        class Connection:
            pending = True
            def __init__(self): self.events = []
            def send(self, event): self.events.append(event)
            def poll(self): return self.pending and any(e['kind'] == 'running' for e in self.events)
            def recv(self):
                self.pending = False
                return {'command': 'stop'}
            def close(self): pass
        conn = Connection()
        worker.worker_entry('run', {'input_id': 0, 'output_id': 1,
                                   'gate': gate, 'output_gain_db': 3, 'battle_mode': battle}, conn)
        kinds = [e['kind'] for e in conn.events]
        assert 'error' not in kinds
        assert kinds.index('benchmark') < kinds.index('running')
    assert measurements == [purity, purity]


def test_benchmark_progress_result_and_explanation_are_visible_in_module(tmp_path, monkeypatch):
    app, w = make_window(tmp_path, monkeypatch)
    try:
        from PySide6.QtWidgets import QLabel
        assert any(l.text() == '点击开始运行时自动测速，切换模式不重测；设备或游戏负载变化后可手动重测'
                   for l in w.findChildren(QLabel))
        w.operation = 'run'
        w.handle_worker_event('progress', {'stage': 'benchmark', 'message': '正在复验最低延迟方案…', 'fraction': .95})
        assert w.bench_summary.text() == '正在复验最低延迟方案…'
        w.handle_worker_event('benchmark', {'selected': {
            'route': Route(0, 1).to_dict(), 'stats': {'estimated_local_ms': 80}}})
        assert '80 ms' in w.bench_summary.text()
        assert not w._benchmark_in_progress
        for event, expected in [('error', '测速失败'), ('cancelled', '测速已取消')]:
            w.handle_worker_event('progress', {'stage': 'benchmark', 'message': '测速中', 'fraction': .2})
            w.handle_worker_event(event, 'interrupted')
            assert w.bench_summary.text() == expected
            assert not w._benchmark_in_progress
    finally:
        close_window(app, w)
