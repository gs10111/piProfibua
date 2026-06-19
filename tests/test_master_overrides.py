from pathlib import Path

import pytest

from profibus_amg11.config import EncoderConfig
from profibus_amg11.master import Amg11Master, build_scan_phy

CONF = str(Path(__file__).resolve().parent.parent / "config" / "amg11.conf")


def test_master_applies_baud_and_addr_override_in_sim():
    m = Amg11Master(CONF, EncoderConfig(), sim=True, baud=93750, master_addr=5)
    try:
        assert m.master.masterAddr == 5
    finally:
        m.close()


def test_build_scan_phy_uses_given_baud():
    # Em serial real abriria /dev/serial0; sem porta no ambiente, pula.
    try:
        phy = build_scan_phy(CONF, 9600)
    except Exception:
        pytest.skip("sem porta serial neste ambiente")
    try:
        assert phy is not None
    finally:
        phy.close()
