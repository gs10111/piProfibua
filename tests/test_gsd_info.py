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
    assert (p.in_size, p.out_size) == (2, 2)   # 0xF0 = 1 word in + 1 word out


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
    assert d["in_size"] == 2 and d["out_size"] == 2


def test_decode_cfg_io_general_format():
    from profibus_amg11.gsd_info import decode_cfg_io
    assert decode_cfg_io(b"") == (0, 0)
    assert decode_cfg_io(b"\xd0") == (2, 0)          # Class 1 Singleturn
    assert decode_cfg_io(b"\xd1") == (4, 0)          # Class 1 Multiturn
    assert decode_cfg_io(b"\xf0") == (2, 2)          # Class 2 Singleturn
    assert decode_cfg_io(b"\xf1") == (4, 4)          # Class 2 Multiturn
    assert decode_cfg_io(b"\xf1\xd0") == (6, 4)      # ifm 2.2 Multiturn


def test_preview_ifm_multiturn_sizes():
    p = preview_params(IFM, ["Class 1 Multiturn"])
    assert (p.in_size, p.out_size) == (4, 0)         # multivolta: lê 4 B, escreve 0
    c2 = preview_params(IFM, ["Class 2 Multiturn"])
    assert (c2.in_size, c2.out_size) == (4, 4)       # Class 2: lê 4 + escreve 4
