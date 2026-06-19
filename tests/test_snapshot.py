from profibus_amg11.scan import Station, StationType
from web.scanner import BusSnapshot, ScanState
from web.settings import BusSettings
from web.snapshot import (Snapshot, bus_snapshot_to_dict, initial_snapshot,
                          snapshot_to_dict)


def test_initial_snapshot_is_connecting():
    s = initial_snapshot(offset=5)
    assert s.connected is False
    assert s.offset == 5
    assert s.diag == "conectando"


def test_snapshot_to_dict_shape_and_rounding():
    s = Snapshot(angle_deg=90.123456, raw=2048, raw_max=8191, bytes_hex="0800", offset=0,
                 connected=True, rate_hz=47.27, diag="OK", ts=123.0)
    d = snapshot_to_dict(s)
    assert d["type"] == "reading"
    assert d["angle_deg"] == 90.123
    assert d["rate_hz"] == 47.3
    assert d["raw"] == 2048
    assert d["raw_max"] == 8191
    assert d["bytes_hex"] == "0800"
    assert d["connected"] is True
    assert set(d.keys()) == {
        "type", "angle_deg", "raw", "raw_max", "bytes_hex", "offset",
        "connected", "rate_hz", "diag", "ts",
    }


def test_bus_snapshot_to_dict_shape():
    bs = BusSnapshot(
        mode="scanning",
        settings=BusSettings(baud=19200, master_addr=2),
        scan_state=ScanState(status="scanning", current_addr=5, scanned=3,
                             total=10,
                             found=(Station(4, StationType.SLAVE, 2.345),)),
        diag="varrendo")
    d = bus_snapshot_to_dict(bs)
    assert d["type"] == "bus"
    assert d["mode"] == "scanning"
    assert d["settings"] == {"baud": 19200, "master_addr": 2}
    assert d["scan"]["status"] == "scanning"
    assert d["scan"]["current_addr"] == 5
    assert d["scan"]["scanned"] == 3 and d["scan"]["total"] == 10
    assert d["scan"]["found"] == [
        {"addr": 4, "station_type": "slave", "response_ms": 2.35}]
