import multiprocessing as mp
import time

from keepquiet.worker import worker_entry


def test_missing_profile_fails_before_audio_can_start(tmp_path, monkeypatch):
    monkeypatch.setenv("KEEPQUIET_DATA_DIR", str(tmp_path))
    parent, child = mp.get_context("spawn").Pipe()
    process = mp.get_context("spawn").Process(target=worker_entry,
        args=("run", {"input_id": -999, "output_id": -999}, child))
    process.start()
    child.close()
    events = []
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if parent.poll(.1):
                    events.append(parent.recv())
                    if events[-1]["kind"] == "finished":
                        break
                elif not process.is_alive():
                    break
            except (EOFError, OSError):
                break
        process.join(timeout=1)
        assert not process.is_alive()
        assert any(e["kind"] == "error" and "声线" in e["value"] for e in events)
        assert not any(e["kind"] == "running" for e in events)
        assert events[-1]["kind"] == "finished"
    finally:
        if process.is_alive():
            process.terminate()
            process.join()
        parent.close()


def test_worker_cancel_drains_non_stop_commands_to_find_stop(monkeypatch):
    from keepquiet import worker
    class FakeConn:
        def __init__(self):
            self.queue = [
                {"command": "metering", "value": False},
                {"command": "output_gain", "value": 3},
                {"command": "stop"},
            ]
            self.sent = []
        def poll(self):
            return bool(self.queue)
        def recv(self):
            return self.queue.pop(0)
        def send(self, msg):
            self.sent.append(msg)
        def close(self):
            pass
    monkeypatch.setattr(worker, "load_models", lambda **kw: object())
    import sounddevice as sd
    monkeypatch.setattr(sd, "query_devices", lambda dev: {"default_samplerate": 16000})
    conn = FakeConn()
    worker.worker_entry("enroll", {"input_id": 0}, conn)
    assert any(e["kind"] == "cancelled" for e in conn.sent)
    assert conn.sent[-1]["kind"] == "finished"
