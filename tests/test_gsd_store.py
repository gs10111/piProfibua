from pathlib import Path

import pytest

from profibus_amg11.gsd_info import GsdInfoError
from web.gsd_store import GsdStore

AMG11 = (Path(__file__).resolve().parent.parent / "gsd" / "PB13DPV0.gsd").read_bytes()


def test_save_validates_and_writes(tmp_path):
    store = GsdStore(tmp_path)
    s = store.save("enc.gsd", AMG11)
    assert s.ident == 0x059B
    assert (tmp_path / "enc.gsd").exists()
    assert store.list() == ["enc.gsd"]


def test_save_rejects_garbage(tmp_path):
    store = GsdStore(tmp_path)
    with pytest.raises(GsdInfoError):
        store.save("bad.gsd", b"nao e gsd")
    assert store.list() == []


def test_save_rejects_unsafe_name(tmp_path):
    store = GsdStore(tmp_path)
    for bad in ("../evil.gsd", "a/b.gsd", "x.txt", "..gsd"):
        with pytest.raises(GsdInfoError):
            store.save(bad, AMG11)


def test_read_roundtrip_and_missing(tmp_path):
    store = GsdStore(tmp_path)
    store.save("enc.gsd", AMG11)
    assert store.read("enc.gsd") == AMG11
    with pytest.raises(FileNotFoundError):
        store.read("nope.gsd")


def test_list_only_gsd(tmp_path):
    (tmp_path / "note.txt").write_text("x")
    store = GsdStore(tmp_path)
    store.save("enc.gsd", AMG11)
    assert store.list() == ["enc.gsd"]


def test_save_rejects_overwrite(tmp_path):
    store = GsdStore(tmp_path)
    store.save("enc.gsd", AMG11)
    with pytest.raises(FileExistsError):
        store.save("enc.gsd", AMG11)
