import pytest

from web.settings import BusSettings, SettingsStore


def test_valid_settings():
    s = BusSettings(baud=19200, master_addr=3)
    assert s.baud == 19200 and s.master_addr == 3


def test_invalid_baud_rejected():
    with pytest.raises(ValueError):
        BusSettings(baud=12345, master_addr=1)


def test_invalid_master_addr_rejected():
    with pytest.raises(ValueError):
        BusSettings(baud=19200, master_addr=0)
    with pytest.raises(ValueError):
        BusSettings(baud=19200, master_addr=127)


def test_load_without_file_returns_defaults(tmp_path):
    store = SettingsStore(tmp_path / "bus.json")
    d = BusSettings(baud=9600, master_addr=2)
    assert store.load(d) == d


def test_save_then_load_roundtrip(tmp_path):
    store = SettingsStore(tmp_path / "bus.json")
    s = BusSettings(baud=93750, master_addr=5)
    store.save(s)
    assert store.load(BusSettings()) == s


def test_corrupt_or_out_of_range_file_falls_back_to_defaults(tmp_path):
    p = tmp_path / "bus.json"
    p.write_text('{"baud": 999, "master_addr": 5}', encoding="utf-8")
    d = BusSettings(baud=19200, master_addr=1)
    assert SettingsStore(p).load(d) == d
    p.write_text("not json", encoding="utf-8")
    assert SettingsStore(p).load(d) == d
