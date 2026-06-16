import pytest

from profibus_amg11.config import EncoderConfig, load_config


def test_defaults():
    c = EncoderConfig()
    assert c.resolution_bits == 13
    assert c.direction == "cw"
    assert c.offset == 0
    assert c.control_word == 0x0000


def test_rejects_bad_direction():
    with pytest.raises(ValueError):
        EncoderConfig(direction="up")


def test_rejects_offset_out_of_range():
    with pytest.raises(ValueError):
        EncoderConfig(resolution_bits=13, offset=8192)   # max valido = 8191


def test_rejects_bad_resolution():
    with pytest.raises(ValueError):
        EncoderConfig(resolution_bits=0)
    with pytest.raises(ValueError):
        EncoderConfig(resolution_bits=17)


def test_rejects_control_word_out_of_range():
    with pytest.raises(ValueError):
        EncoderConfig(control_word=0x10000)


def test_load_from_yaml(tmp_path):
    p = tmp_path / "enc.yaml"
    p.write_text(
        "resolution_bits: 13\n"
        "direction: ccw\n"
        "offset: 100\n"
        "control_word: 0x0000\n"
    )
    c = load_config(str(p))
    assert c.direction == "ccw"
    assert c.offset == 100
    assert c.control_word == 0


def test_load_empty_yaml_uses_defaults(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    c = load_config(str(p))
    assert c == EncoderConfig()
