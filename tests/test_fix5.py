from contextlib import nullcontext
from types import SimpleNamespace
import os
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from keepquiet.devices import Route
from test_profiles import make_window, close_window


@pytest.mark.parametrize('invalid', [
    {'custom_filter_mode': []}, {'filter_mode': {}}, {'purity_mode': []},
    {'input_device': 'bad'}, {'output_device': {'endpoint_id': 'missing-host'}},
    {'last_driver_check': 'bad'}, {'last_driver_check': -1},
    {'output_gain_db': float('nan')}, {'profile_schema': True},
    {'check_driver_updates': 'false'}, {'custom_gate_threshold_db': [1]},
])
def test_invalid_fields_recover_without_discarding_valid_settings(tmp_path, monkeypatch, invalid):
    data = {'profile_schema': 1, 'theme': 'light', 'retained_extension': 'keep', **invalid}
    original = json.dumps(data).encode('utf-8')
    (tmp_path/'settings.json').write_bytes(original)
    app, w = make_window(tmp_path, monkeypatch)
    try:
        assert w.settings_recovered and w.theme == 'light'
        assert w.settings['retained_extension'] == 'keep'
        backups = list(tmp_path.glob('settings.json.invalid-*'))
        assert len(backups) == 1 and backups[0].read_bytes() == original
        assert isinstance(w.custom_filter_mode, str)
        w.screenshot_mode = False
        w.launch = lambda *a, **kw: None
        w.first_run()  # A bad timestamp must not crash the delayed check either.
    finally:
        close_window(app, w)


@pytest.fixture
def session(tmp_path, monkeypatch):
    from keepquiet import ui
    app, w = make_window(tmp_path, monkeypatch)
    w.refresh_devices = lambda: None
    w.input_combo.addItem('input', 0)
    w.output_combo.addItem('output', 1)
    (tmp_path/'voiceprint.protected').write_bytes(b'test-only-placeholder')
    processes = []
    class Connection:
        def __init__(self): self.sent = []; self.closed = False
        def send(self, message): self.sent.append(message)
        def poll(self): return False
        def close(self): self.closed = True
    class Process:
        pid = os.getpid()
        exitcode = 0
        def __init__(self, *, target, args, daemon):
            self.mode, self.config, _ = args
            self.alive = False
            processes.append(self)
        def start(self): self.alive = True
        def is_alive(self): return self.alive
        def join(self, **kw): pass
        def terminate(self): self.alive = False
    context = SimpleNamespace(Pipe=lambda: (Connection(), SimpleNamespace(close=lambda: None)), Process=Process)
    monkeypatch.setattr(ui.mp, 'get_context', lambda *a: context)
    yield w, processes
    w.proc = w.conn = None
    close_window(app, w)


def ready(w, *, muted=False):
    w.handle_worker_event('running', {'route': Route(0, 1).to_dict(), 'muted': muted})


def finish(w, proc):
    w.handle_worker_event('finished', {})
    proc.alive = False
    w.poll()


def test_mode_switch_reuses_route_and_keeps_mute_monitor_profile(session):
    w, processes = session
    w.launch('run')
    initial = processes[0].config.copy()
    ready(w)
    w.toggle_mute()
    w.handle_worker_event('monitor', {'enabled': True})
    first_connection = w.conn
    w.battle_button.click()
    assert w._restart_pending and not w.running
    assert first_connection.sent[-1] == {'command': 'stop'}
    assert not w.battle_button.isEnabled()
    finish(w, processes[0])
    assert len(processes) == 2 and first_connection.closed
    assert 'resume_route' not in processes[0].config
    assert processes[1].config['resume_route'] == Route(0, 1).to_dict()
    assert processes[1].config['battle_mode'] is True
    assert processes[1].config['muted'] is True and processes[1].config['monitor'] is True
    assert processes[1].config['gate'] == initial['gate']
    ready(w, muted=True)
    assert w.muted and w.mute.text() == '恢复声音'
    w.handle_worker_event('monitor', {'enabled': True})
    w.battle_button.click()
    finish(w, processes[1])
    assert len(processes) == 3
    assert processes[2].config['battle_mode'] is False
    assert processes[2].config['gate'] == initial['gate']
    assert processes[2].config['output_gain_db'] == initial['output_gain_db']
    assert processes[2].config['muted'] is True
    assert not w._benchmark_in_progress


def test_preparation_cannot_change_the_measured_mode(session):
    w, processes = session
    w.launch('run')
    QTest.mouseClick(w.battle_button, Qt.MouseButton.LeftButton)
    QTest.keyClick(w.battle_button, Qt.Key.Key_Space)
    QTest.mouseClick(w.purity_combo, Qt.MouseButton.LeftButton)
    assert not w.battle_enabled and not w.purity_combo.view().isVisible()
    assert not w.gate_value.isEnabled() and not w.custom_dialog.filter_combo.isEnabled()
    assert processes[0].config['battle_mode'] is False
    ready(w)
    assert w.battle_button.isEnabled() and w.purity_combo.isEnabled()


@pytest.mark.parametrize('end_reason', ['stop', 'error'])
def test_stopping_or_error_cancels_queued_restart(session, end_reason):
    w, processes = session
    w.launch('run')
    ready(w)
    w.battle_button.click()
    assert w._restart_pending
    if end_reason == 'stop':
        w.stop_worker()
    else:
        w.handle_worker_event('error', 'device failed')
    finish(w, processes[0])
    assert len(processes) == 1 and not w._restart_pending
    assert not w._benchmark_in_progress


@pytest.mark.parametrize('change', ['preset', 'filter'])
def test_preset_and_filter_changes_reuse_current_route(session, change):
    w, processes = session
    w.launch('run')
    ready(w)
    if change == 'preset':
        w.purity_combo.setCurrentIndex(w.purity_combo.findData('ultra'))
    else:
        # Enter the custom panel while idle, then test the actual filter change.
        w.running = False
        w.purity_combo.setCurrentIndex(w.purity_combo.findData('custom'))
        w.running = True
        w.custom_dialog.filter_combo.setCurrentIndex(1)
    assert w._restart_pending and not w.running
    finish(w, processes[0])
    assert len(processes) == 2 and processes[1].config['gate']['purity'] == 'ultra'
    assert processes[1].config['resume_route'] == Route(0, 1).to_dict()
    assert not w._benchmark_in_progress


def test_battle_manual_benchmark_never_loads_models_or_voice(monkeypatch):
    from keepquiet import worker
    calls, events = [], []
    def forbidden(*a, **kw): raise AssertionError('No model or voice loading in battle measurement')
    monkeypatch.setattr(worker, 'load_models', forbidden)
    monkeypatch.setattr(worker, 'load_voiceprint', forbidden)
    monkeypatch.setattr(worker, 'read_json', lambda *a: {})
    monkeypatch.setattr(worker, 'audio_priority', lambda: nullcontext({}))
    def measure(a, b, models, voice, **kw):
        assert models is voice is None and kw['battle_mode'] is True
        calls.append(True)
    monkeypatch.setattr(worker, 'run_benchmark', measure)
    conn = SimpleNamespace(send=events.append, close=lambda: None)
    worker.worker_entry('benchmark', {'input_id': 0, 'output_id': 1, 'battle_mode': True}, conn)
    assert calls == [True] and not any(e['kind'] == 'error' for e in events)


@pytest.mark.parametrize('resume', [False, True])
@pytest.mark.parametrize('battle', [False, True])
def test_cancel_before_output_reports_the_actual_operation(monkeypatch, resume, battle):
    from keepquiet import worker
    events = []
    def forbidden(*a, **kw): raise AssertionError('Cancelled startup opened live output')
    monkeypatch.setattr(worker, 'Bridge', forbidden)
    monkeypatch.setattr(worker, 'load_models', lambda **kw: {})
    monkeypatch.setattr(worker, 'load_voiceprint', lambda: object())
    monkeypatch.setattr(worker, 'read_json', lambda *a: {})
    monkeypatch.setattr(worker, 'audio_priority', lambda: nullcontext({}))
    measured = []
    def measure(*args, **kwargs):
        assert not resume, 'Mode switch must not benchmark'
        measured.append(True)
        return Route(0, 1), {}
    monkeypatch.setattr(worker, 'run_benchmark', measure)
    commands = [{'command': 'stop'}]
    conn = SimpleNamespace(send=events.append, poll=lambda: bool(commands), recv=lambda: commands.pop(), close=lambda: None)
    config = {'input_id': 0, 'output_id': 1, 'battle_mode': battle}
    if resume:
        config['resume_route'] = Route(0, 1).to_dict()
    worker.worker_entry('run', config, conn)
    expected = '模式切换已取消。' if resume else '测速已取消。'
    assert [e['value'] for e in events if e['kind'] == 'cancelled'] == [expected]
    assert measured == ([] if resume else [True])
    assert not any(e['kind'] in ('running', 'error') for e in events)


@pytest.mark.parametrize('resume', [False, True])
@pytest.mark.parametrize('battle', [False, True])
def test_restarted_worker_applies_mute_before_running_and_restores_monitor(monkeypatch, resume, battle):
    from keepquiet import worker
    order, events = [], []
    class FakeBridge:
        monitor_error = None
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def set_metering(self, value): pass
        def set_muted(self, value): order.append(('mute', value))
        def set_monitor(self, value):
            order.append(('monitor', value))
            return value
    def send(e):
        events.append(e)
        order.append(e['kind'])
    pending = [True]
    def receive():
        pending.clear()
        return {'command': 'stop'}
    conn = SimpleNamespace(send=send, poll=lambda: bool(pending) and any(e['kind'] == 'running' for e in events),
                           recv=receive, close=lambda: None)
    monkeypatch.setattr(worker, 'Bridge', FakeBridge)
    monkeypatch.setattr(worker, 'read_json', lambda *a: {})
    monkeypatch.setattr(worker, 'audio_priority', lambda: nullcontext({}))
    monkeypatch.setattr(worker, 'run_benchmark', lambda *a, **kw: (Route(0, 1), {}))
    def measure(*args, **kwargs):
        assert not resume, 'Mode switch must not run a benchmark'
        return Route(0, 1), {}
    monkeypatch.setattr(worker, 'run_benchmark', measure)
    monkeypatch.setattr(worker, 'load_models', lambda **kw: {})
    monkeypatch.setattr(worker, 'load_voiceprint', lambda: object())
    config = {'input_id': 0, 'output_id': 1, 'battle_mode': battle, 'muted': True, 'monitor': True}
    if resume:
        config['resume_route'] = Route(0, 1).to_dict()
    worker.worker_entry('run', config, conn)
    assert order.index(('mute', True)) < order.index('running')
    assert any(e['kind'] == 'running' and e['value']['muted'] is True for e in events)
    assert any(e['kind'] == 'monitor' and e['value']['enabled'] is True for e in events)
    assert not any(e['kind'] == 'error' for e in events)


def test_mode_restart_rejects_changed_devices_without_opening_stream(monkeypatch):
    from keepquiet import worker
    events = []
    def forbidden(*args, **kwargs):
        raise AssertionError('Changed device route must not open output or benchmark')
    monkeypatch.setattr(worker, 'Bridge', forbidden)
    monkeypatch.setattr(worker, 'run_benchmark', forbidden)
    monkeypatch.setattr(worker, 'read_json', lambda *a: {})
    monkeypatch.setattr(worker, 'audio_priority', lambda: nullcontext({}))
    conn = SimpleNamespace(send=events.append, close=lambda: None)
    worker.worker_entry('run', {'input_id': 9, 'output_id': 1, 'battle_mode': True,
                               'resume_route': Route(0, 1).to_dict()}, conn)
    assert any(e['kind'] == 'error' for e in events)
    assert not any(e['kind'] == 'running' for e in events)


def test_explicit_start_after_mode_switch_measures_again(session):
    w, processes = session
    w.launch('run')
    ready(w)
    w.battle_button.click()
    finish(w, processes[0])
    assert 'resume_route' in processes[1].config
    ready(w)
    w.stop_worker()
    finish(w, processes[1])
    w.launch('run')
    assert len(processes) == 3
    assert 'resume_route' not in processes[2].config
    assert w._benchmark_in_progress


def test_running_custom_editor_survives_mode_and_filter_restarts(session):
    from PySide6.QtWidgets import QApplication
    w, processes = session
    w.launch('run')
    ready(w)
    index = w.purity_combo.findData('custom')
    w.purity_combo.setCurrentIndex(index)
    w._open_custom_on_selection(index)
    QApplication.processEvents()
    assert w.custom_dialog.isVisible()
    assert not w.gate_value.isEnabled()
    finish(w, processes[0])
    assert w.custom_dialog.isVisible()
    assert not w.gate_value.isEnabled()
    ready(w)
    assert w.custom_dialog.isVisible() and w.gate_value.isEnabled()
    w.custom_dialog.filter_combo.setCurrentIndex(1)
    assert w._restart_pending and w.custom_dialog.isVisible()
    finish(w, processes[1])
    assert w.custom_dialog.isVisible()
    ready(w)
    assert w.custom_dialog.isVisible() and w.gate_value.isEnabled()


def test_custom_editor_closed_by_user_is_not_reopened_on_restart(session):
    from PySide6.QtWidgets import QApplication
    w, processes = session
    w.launch('run')
    ready(w)
    index = w.purity_combo.findData('custom')
    w.purity_combo.setCurrentIndex(index)
    w._open_custom_on_selection(index)
    QApplication.processEvents()
    assert w.custom_dialog.isVisible()
    w.custom_dialog.close()
    finish(w, processes[0])
    ready(w)
    assert not w.custom_dialog.isVisible()
