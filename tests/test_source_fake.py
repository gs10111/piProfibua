from profibus_amg11.config import EncoderConfig
from profibus_amg11.master import Amg11Master
from profibus_amg11.source import ReadingSource
from fakes import FakeSource


def test_fakesource_conforms_and_emits():
    src = FakeSource([0x0800, 0x1000])  # 90°, 180°
    assert isinstance(src, ReadingSource)  # Protocol runtime check
    assert src.poll().raw == 0x0800
    assert src.poll().raw == 0x1000
    assert src.poll().raw == 0x0800       # cicla


def test_fakesource_none_entry_returns_none():
    src = FakeSource([0x0800, None])
    assert src.poll().raw == 0x0800
    assert src.poll() is None


def test_fakesource_set_offset_changes_decode():
    src = FakeSource([0x0800])            # raw bruto 2048
    src.set_offset(0x0800)               # zera nesse ponto
    assert src.poll().raw == 0           # (2048 - 2048) mod 8192


def test_fakesource_close():
    src = FakeSource([0x0800])
    src.close()
    assert src.closed is True


def test_amg11master_set_offset_applies_in_sim():
    cfg = EncoderConfig(control_word=0xFFFF)   # dummy devolve 0x0000 -> raw 0
    m = Amg11Master("config/amg11.conf", cfg, sim=True)
    try:
        m.set_offset(100)
        assert m.encoder_cfg.offset == 100
        r = m.read_once(timeout=5.0)
        assert r.raw == (0 - 100) % 8192       # 8092
    finally:
        m.close()
