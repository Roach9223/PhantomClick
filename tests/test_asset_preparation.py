import threading
import time

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from ui.asset_preparation import AssetPreparation


def pump_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents(QEventLoop.AllEvents, 10)
        time.sleep(0.005)
    assert predicate(), "background work did not finish"


def test_network_work_is_off_gui_thread_and_reports_failures(tmp_path):
    qt = QApplication.instance() or QApplication([])
    gui_thread = threading.get_ident()
    calls, result = [], []
    class Client:
        def fetch_item_image(self, name):
            calls.append((name, threading.get_ident()))
            raise TimeoutError("offline")
    job = AssetPreparation(["Trout"], tmp_path, client_factory=lambda _: Client())
    job.completed.connect(result.append)
    job.start()
    pump_until(lambda: bool(result))
    assert calls[0][1] != gui_thread
    assert "offline" in result[0][0]


def test_cancel_prevents_remaining_downloads(tmp_path):
    qt = QApplication.instance() or QApplication([])
    entered, release = threading.Event(), threading.Event()
    calls, result = [], []
    class Client:
        def fetch_item_image(self, name):
            calls.append(name)
            entered.set()
            release.wait(2)
            return tmp_path / "image.png"
    job = AssetPreparation(["Trout", "Salmon"], tmp_path, client_factory=lambda _: Client())
    job.completed.connect(result.append)
    job.start()
    pump_until(entered.is_set)
    job.cancel()
    release.set()
    pump_until(lambda: bool(result))
    assert calls == ["Trout"]


def test_cached_assets_do_not_download(tmp_path):
    qt = QApplication.instance() or QApplication([])
    from ai.wiki.client import _slugify
    (tmp_path / "items").mkdir()
    (tmp_path / "items" / f"{_slugify('Trout')}.png").write_bytes(b"cached")
    class Client:
        def fetch_item_image(self, name):
            raise AssertionError("cache hit must not use network")
    result = []
    job = AssetPreparation(["Trout"], tmp_path, client_factory=lambda _: Client())
    job.completed.connect(result.append)
    job.start()
    pump_until(lambda: bool(result))
    assert result == [[]]
