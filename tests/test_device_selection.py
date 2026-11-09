from keepquiet import devices as module


def device(number=1, endpoint='capture-original', name='麦克风'):
    return dict(id=number, endpoint_id=endpoint, name=name, host='Windows WASAPI',
                inputs=1, outputs=0, rate=48000, virtual=False)


def test_saved_endpoint_survives_number_and_name_changes():
    saved = module.selection_key(device())
    changed = device(27, name='用户重命名的麦克风')
    assert module.find_selection([device(1, 'other'), changed], saved) == changed


def test_missing_endpoint_never_falls_back_to_same_name_or_number():
    saved = module.selection_key(device())
    assert module.find_selection([device(1, 'different-hardware')], saved) is None


def test_fallback_identity_requires_unique_name_and_host():
    saved = dict(name='麦克风', host='Windows WASAPI')
    assert module.find_selection([device()], saved)['id'] == 1
    assert module.find_selection([device(), device(2)], saved) is None


def test_external_driver_upgrade_invalidates_fingerprint(monkeypatch):
    from keepquiet import driver
    monkeypatch.setattr(module, 'devices', lambda: [device(1), device(2, 'render')])
    info = {'DeviceName': 'VB-Audio Virtual Cable', 'DriverVersion': '3.3.1.7', 'InfName': 'oem1.inf'}
    monkeypatch.setattr(driver, 'installed_driver', lambda: dict(info))
    before = module.fingerprint(1, 2)
    info['DriverVersion'] = '3.5.2.0'
    assert before != module.fingerprint(1, 2)


def test_fast_registry_queries_avoid_spawning_powershell_on_windows(monkeypatch):
    import sys
    if sys.platform != 'win32':
        return
    from keepquiet import driver
    def forbid_powershell(*args, **kwargs):
        raise AssertionError('Should not spawn powershell when registry succeeds')
    monkeypatch.setattr(driver, 'powershell', forbid_powershell)
    endpoints = module.endpoint_ids()
    assert isinstance(endpoints, list) and len(endpoints) > 0
    assert all('Name' in e and e['DeviceID'].startswith('SWD\\MMDEVAPI\\') for e in endpoints)
    drv = driver.installed_driver()
    assert drv is None or ('DeviceName' in drv and 'DriverVersion' in drv and 'InfName' in drv)


def test_manual_driver_policy_and_persisted_device_restore(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    monkeypatch.setenv('KEEPQUIET_DATA_DIR', str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from keepquiet import ui
    from keepquiet.storage import write_json, read_json
    output = dict(id=2, endpoint_id='cable', name='CABLE Input', host='Windows WASAPI', inputs=0, outputs=2, virtual=True, rate=48000)
    items = [device(), output]
    monkeypatch.setattr(ui, 'devices', lambda **kwargs: items)
    write_json(tmp_path/'settings.json', {'auto_driver': True, 'input_device':module.selection_key(items[0]), 'output_device':module.selection_key(output)})
    app = QApplication.instance() or QApplication([])
    ui.configure_app(app)
    w = ui.Window()
    w.screenshot_mode = True
    assert w.input_combo.currentData() == 1
    items[0] = device(27)
    w.refresh_devices()
    assert w.input_combo.currentData() == 27
    items[:] = [device(27, 'wrong-microphone'), output]
    w.refresh_devices()
    assert w.input_combo.currentIndex() == -1
    assert '未找到上次' in w.message.text()
    items[0] = device(30)
    w.refresh_devices()
    assert w.input_combo.currentData() == 30
    calls = []
    w.launch = lambda mode, **kwargs: calls.append(mode)
    w.screenshot_mode = False
    w.first_run()
    assert calls == ['driver_check']
    w.handle_worker_event('driver', {'available':True, 'version':'9.9.9.9'})
    assert calls == ['driver_check']  # No automatic install, even with legacy opt-in.
    assert '手动' in w.message.text()
    items[:] = [device(30)]
    w.refresh_devices()
    calls.clear()
    w.settings['last_driver_check'] = 0
    w.first_run()
    assert not calls  # Missing driver prompts installation rather than initiating UAC.
    assert read_json(tmp_path/'settings.json')['input_device']['endpoint_id'] == 'capture-original'
    # Simulate an actual stream-disconnect event and completed worker lifecycle.
    from types import SimpleNamespace
    w.operation = 'run'
    w.proc = SimpleNamespace(is_alive=lambda:False, join=lambda **kwargs:None, exitcode=0)
    w.conn = SimpleNamespace(poll=lambda:False, close=lambda:None)
    w.handle_worker_event('device_lost', '音频设备已断开')
    w.handle_worker_event('error', '音频设备已断开')
    w.handle_worker_event('finished', {})
    w.poll()
    assert w.start.text() == '重新运行'
    assert w.output_combo.currentIndex() == -1
    assert not w.running
    items.append(output)
    w.refresh_devices()
    assert w.input_combo.currentData() == 30 and w.output_combo.currentData() == 2
    assert '重新运行' in w.message.text()
    w.screenshot_mode = True
    w.exit_app()
    w.deleteLater()
    app.processEvents()


def test_device_enumeration_only_exposes_wasapi(monkeypatch):
    import sounddevice as sd
    monkeypatch.setattr(sd, 'query_hostapis', lambda: [
        {'name': 'MME'}, {'name': 'Windows DirectSound'}, {'name': 'Windows WASAPI'}])
    monkeypatch.setattr(sd, 'query_devices', lambda: [
        {'name': 'Same microphone', 'hostapi': i, 'max_input_channels': 1,
         'max_output_channels': 0, 'default_samplerate': 48000} for i in range(3)])
    monkeypatch.setattr(module, 'endpoint_ids', lambda: [])
    items = module.devices()
    assert len(items) == 1 and items[0]['id'] == 2
    assert items[0]['host'] == 'Windows WASAPI'
