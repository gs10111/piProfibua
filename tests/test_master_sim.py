from pathlib import Path

import pytest

from profibus_amg11.config import EncoderConfig
from profibus_amg11.master import Amg11Master

ROOT = Path(__file__).resolve().parent.parent
CONF = str(ROOT / "config" / "amg11.conf")


def test_sim_reads_known_position():
    # O PHY dummy responde ao Data_Exchange com (control_word XOR 0xFFFF).
    # control_word=0xFFFF -> dummy devolve 0x0000 -> raw 0, angulo 0.
    cfg = EncoderConfig(control_word=0xFFFF)
    m = Amg11Master(CONF, cfg, sim=True)
    try:
        r = m.read_once(timeout=5.0)
    finally:
        m.close()
    assert r.raw == 0
    assert r.angle_deg == pytest.approx(0.0)


def test_sim_reads_other_position():
    # control_word=0xF000 -> dummy devolve 0x0FFF -> raw 0x0FFF (4095).
    cfg = EncoderConfig(control_word=0xF000)
    m = Amg11Master(CONF, cfg, sim=True)
    try:
        r = m.read_once(timeout=5.0)
    finally:
        m.close()
    assert r.raw == 0x0FFF
    assert r.angle_deg == pytest.approx(4095 / 8192 * 360.0)


def test_sim_run_callback_then_stop():
    cfg = EncoderConfig(control_word=0xFFFF)
    m = Amg11Master(CONF, cfg, sim=True)
    seen = []

    def cb(reading):
        seen.append(reading)
        if len(seen) >= 3:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        m.run(cb, hz=200.0)
    assert len(seen) >= 3
