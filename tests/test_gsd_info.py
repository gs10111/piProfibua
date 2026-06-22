from pathlib import Path

import pytest

from profibus_amg11.gsd_info import (GsdInfoError, parse_gsd, preview_params,
                                     preview_to_dict, summary_to_dict)

GSD = Path(__file__).resolve().parent.parent / "gsd"
AMG11 = (GSD / "PB13DPV0.gsd").read_bytes()
IFM = (GSD / "IFM_0E75.gsd").read_bytes()


def test_parse_amg11_metadata():
    s = parse_gsd(AMG11, "PB13DPV0.gsd")
    assert s.ident == 0x059B
    assert "Baumer" in s.vendor
    assert s.modular is True
    names = [m.name for m in s.modules]
    assert any("16 Bit Class 2" in n for n in names)
    assert s.max_tsdr[19200] == 60


def test_parse_ifm_metadata():
    s = parse_gsd(IFM, "IFM_0E75.gsd")
    assert s.ident == 0x0E75
    assert "ifm" in s.vendor.lower()
    assert len(s.modules) >= 6


def test_parse_invalid_raises():
    with pytest.raises(GsdInfoError):
        parse_gsd(b"isto nao e um gsd", "bad.gsd")


def test_preview_amg11_class2_module():
    p = preview_params(AMG11, ["16 Bit Class 2 Encoder "])
    assert p.ident == 0x059B
    assert p.cfg_hex == "f0"
    assert p.user_prm_hex.startswith("000a")


def test_preview_unknown_module_raises():
    with pytest.raises(GsdInfoError):
        preview_params(AMG11, ["modulo inexistente"])


def test_summary_to_dict_shape():
    d = summary_to_dict(parse_gsd(AMG11, "PB13DPV0.gsd"))
    assert d["ident_hex"] == "0x059B"
    assert d["filename"] == "PB13DPV0.gsd"
    assert isinstance(d["modules"], list)
    assert d["modules"][0].keys() >= {"name", "config_hex", "preset"}
    assert d["max_tsdr"]["19200"] == 60


def test_preview_to_dict_shape():
    d = preview_to_dict(preview_params(AMG11, ["16 Bit Class 2 Encoder "]))
    assert d["ident_hex"] == "0x059B" and d["cfg_hex"] == "f0"
    assert d["modules"] == ["16 Bit Class 2 Encoder "]
