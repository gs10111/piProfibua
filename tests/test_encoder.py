import pytest

from profibus_amg11.encoder import decode, EncoderReading
from profibus_amg11.config import EncoderConfig


def cfg(**kw):
    base = dict(resolution_bits=13, direction="cw", offset=0, control_word=0x0000)
    base.update(kw)
    return EncoderConfig(**base)


@pytest.mark.parametrize("raw16, expected_deg", [
    (0x0000, 0.0),
    (0x0800, 90.0),     # 2048 / 8192 * 360
    (0x1000, 180.0),    # 4096 / 8192 * 360
    (0x1800, 270.0),    # 6144 / 8192 * 360
])
def test_decode_cw_angles(raw16, expected_deg):
    data = raw16.to_bytes(2, "big")
    r = decode(data, cfg())
    assert isinstance(r, EncoderReading)
    assert r.raw == (raw16 & 0x1FFF)
    assert r.angle_deg == pytest.approx(expected_deg, abs=1e-6)


def test_decode_masks_to_13_bits():
    # bits acima do 13o (0xE000) devem ser ignorados
    r = decode((0xE800).to_bytes(2, "big"), cfg())
    assert r.raw == 0x0800
    assert r.angle_deg == pytest.approx(90.0)


def test_decode_ccw_mirrors_angle():
    r = decode((0x0800).to_bytes(2, "big"), cfg(direction="ccw"))
    assert r.raw == 0x1800           # 8192 - 2048
    assert r.angle_deg == pytest.approx(270.0)


def test_decode_offset_zeroes_reference():
    r = decode((0x0800).to_bytes(2, "big"), cfg(offset=0x0800))
    assert r.raw == 0
    assert r.angle_deg == pytest.approx(0.0)


def test_decode_offset_wraps():
    r = decode((0x0000).to_bytes(2, "big"), cfg(offset=0x0800))
    assert r.raw == 0x1800           # (0 - 2048) mod 8192
    assert r.angle_deg == pytest.approx(270.0)


def test_decode_rejects_wrong_length():
    with pytest.raises(ValueError):
        decode(b"\x00", cfg())
    with pytest.raises(ValueError):
        decode(b"\x00\x00\x00", cfg())
