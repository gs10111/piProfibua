from web.snapshot import Snapshot, initial_snapshot, snapshot_to_dict


def test_initial_snapshot_is_connecting():
    s = initial_snapshot(offset=5)
    assert s.connected is False
    assert s.offset == 5
    assert s.diag == "conectando"


def test_snapshot_to_dict_shape_and_rounding():
    s = Snapshot(angle_deg=90.123456, raw=2048, bytes_hex="0800", offset=0,
                 connected=True, rate_hz=47.27, diag="OK", ts=123.0)
    d = snapshot_to_dict(s)
    assert d["type"] == "reading"
    assert d["angle_deg"] == 90.123
    assert d["rate_hz"] == 47.3
    assert d["raw"] == 2048
    assert d["bytes_hex"] == "0800"
    assert d["connected"] is True
    assert set(d.keys()) == {
        "type", "angle_deg", "raw", "bytes_hex", "offset",
        "connected", "rate_hz", "diag", "ts",
    }
