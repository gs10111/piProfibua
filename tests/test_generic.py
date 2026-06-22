from pathlib import Path

import pytest

from profibus_amg11.generic import (GenericDpMaster, GenericError,
                                    make_generic_slave_desc)

GSD = Path(__file__).resolve().parent.parent / "gsd"
AMG11 = (GSD / "PB13DPV0.gsd").read_bytes()
IFM = (GSD / "IFM_0E75.gsd").read_bytes()
CONF = str(Path(__file__).resolve().parent.parent / "config" / "amg11.conf")


def test_slave_desc_from_amg11():
    d = make_generic_slave_desc(AMG11, 3, ["16 Bit Class 2 Encoder "], 2, 2)
    assert d.identNumber == 0x059B
    assert d.slaveAddr == 3
    assert d.inputSize == 2 and d.outputSize == 2


def test_slave_desc_from_ifm():
    s = make_generic_slave_desc(IFM, 9, ["Class 2 Multiturn"], 4, 0)
    assert s.identNumber == 0x0E75 and s.slaveAddr == 9


def test_unknown_module_raises():
    with pytest.raises(GenericError):
        make_generic_slave_desc(AMG11, 3, ["nao existe"], 2, 2)


def test_generic_master_constructs_in_sim():
    m = GenericDpMaster(CONF, AMG11, 3, ["16 Bit Class 2 Encoder "], 2, 2, sim=True)
    try:
        assert isinstance(m.connected, bool)
        m.set_output(b"\x00\x00")
        m.poll()  # não deve lançar
    finally:
        m.close()
