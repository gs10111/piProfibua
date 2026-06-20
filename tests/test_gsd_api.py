import io
import json
from pathlib import Path

from web.scanner import BusSnapshot, ScanState
from web.server import create_app
from web.gsd_store import GsdStore
from web.settings import BusSettings
from web.snapshot import initial_snapshot

AMG11 = (Path(__file__).resolve().parent.parent / "gsd" / "PB13DPV0.gsd").read_bytes()


class FakeController:
    def encoder_snapshot(self):
        return initial_snapshot()

    def bus_snapshot(self):
        return BusSnapshot("exchange", BusSettings(), ScanState(), "ok")

    def zero(self):
        pass

    def clear_zero(self):
        pass

    def scan(self):
        pass

    def apply_settings(self, b, m):
        pass


def make_client(tmp_path):
    app = create_app(FakeController(), gsd_store=GsdStore(tmp_path))
    return app.test_client()


def _upload(client, name=b"enc.gsd", data=AMG11):
    return client.post("/api/gsd",
                       data={"file": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def test_upload_and_list(tmp_path):
    c = make_client(tmp_path)
    r = _upload(c)
    assert r.status_code == 200
    assert r.get_json()["ident_hex"] == "0x059B"
    r = c.get("/api/gsd")
    assert [g["filename"] for g in r.get_json()["gsds"]] == ["enc.gsd"]


def test_upload_invalid_returns_400(tmp_path):
    c = make_client(tmp_path)
    r = _upload(c, name=b"bad.gsd", data=b"lixo")
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_get_one_and_missing(tmp_path):
    c = make_client(tmp_path)
    _upload(c)
    assert c.get("/api/gsd/enc.gsd").get_json()["ident_hex"] == "0x059B"
    assert c.get("/api/gsd/nope.gsd").status_code == 404


def test_preview_endpoint(tmp_path):
    c = make_client(tmp_path)
    _upload(c)
    r = c.post("/api/gsd/enc.gsd/preview",
               data=json.dumps({"modules": ["16 Bit Class 2 Encoder "]}),
               content_type="application/json")
    assert r.status_code == 200
    assert r.get_json()["cfg_hex"] == "f0"


def test_preview_unknown_module_returns_400(tmp_path):
    c = make_client(tmp_path)
    _upload(c)
    r = c.post("/api/gsd/enc.gsd/preview",
               data=json.dumps({"modules": ["nao existe"]}),
               content_type="application/json")
    assert r.status_code == 400


def test_gsd_routes_absent_without_store(tmp_path):
    app = create_app(FakeController())
    assert app.test_client().get("/api/gsd").status_code == 404
