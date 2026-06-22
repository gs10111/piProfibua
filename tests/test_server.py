import json

from web.scanner import BusSnapshot, ScanState
from web.server import create_app, handle_ws_message
from web.settings import BusSettings
from web.snapshot import initial_snapshot


class FakeController:
    def __init__(self):
        self.calls = []

    def encoder_snapshot(self):
        return initial_snapshot()

    def bus_snapshot(self):
        return BusSnapshot("exchange", BusSettings(), ScanState(), "ok")

    def zero(self):
        self.calls.append(("zero",))

    def clear_zero(self):
        self.calls.append(("clear_zero",))

    def scan(self):
        self.calls.append(("scan",))

    def apply_settings(self, baud, master_addr):
        self.calls.append(("apply", baud, master_addr))


def test_index_served():
    app = create_app(FakeController())
    resp = app.test_client().get("/")
    assert resp.status_code == 200
    assert b'id="app"' in resp.data


def test_static_route_is_clean():
    app = create_app(FakeController())
    resp = app.test_client().get("/styles.css")
    assert resp.status_code in (200, 404)


def test_handle_zero_and_scan():
    c = FakeController()
    handle_ws_message(c, json.dumps({"cmd": "zero"}))
    handle_ws_message(c, json.dumps({"cmd": "scan"}))
    assert c.calls == [("zero",), ("scan",)]


def test_handle_apply_settings():
    c = FakeController()
    handle_ws_message(c, json.dumps({"cmd": "apply_settings",
                                     "baud": 9600, "master_addr": 3}))
    assert c.calls == [("apply", 9600, 3)]


def test_handle_invalid_messages_ignored():
    c = FakeController()
    handle_ws_message(c, "not json")
    handle_ws_message(c, json.dumps({"cmd": "apply_settings", "baud": "x"}))
    handle_ws_message(c, json.dumps({"nope": 1}))
    assert c.calls == []
