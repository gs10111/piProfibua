from pathlib import Path

import pytest

from profibus_amg11.generic import (GenericDpMaster, GenericError,
                                    make_generic_slave_desc)

GSD = Path(__file__).resolve().parent.parent / "gsd"
AMG11 = (GSD / "PB13DPV0.gsd").read_bytes()
IFM = (GSD / "IFM_0E75.gsd").read_bytes()
CONF = str(Path(__file__).resolve().parent.parent / "config" / "amg11.conf")


def test_slave_desc_from_amg11():
    d = make_generic_slave_desc(AMG11, 3, ["16 Bit Class 2 Encoder "])
    assert d.identNumber == 0x059B
    assert d.slaveAddr == 3
    assert d.inputSize == 2 and d.outputSize == 2   # 0xF0 simétrico


def test_slave_desc_derives_and_flips_multiturn():
    # Class 2 Multiturn (0xF1): mestre LÊ 4 B (posição) e ESCREVE 4 B (preset).
    # pyprofibus é escravo-cêntrico: outputSize=read, inputSize=write.
    c2 = make_generic_slave_desc(IFM, 9, ["Class 2 Multiturn"])
    assert c2.identNumber == 0x0E75 and c2.slaveAddr == 9
    assert c2.outputSize == 4 and c2.inputSize == 4


def test_unknown_module_raises():
    with pytest.raises(GenericError):
        make_generic_slave_desc(AMG11, 3, ["nao existe"])


def test_generic_master_constructs_in_sim():
    m = GenericDpMaster(CONF, AMG11, 3, ["16 Bit Class 2 Encoder "], sim=True)
    try:
        assert isinstance(m.connected, bool)
        assert (m.input_size, m.output_size) == (2, 2)   # derivado do 0xF0
        m.set_output(b"\x00\x00")
        m.poll()  # não deve lançar
    finally:
        m.close()


def test_readonly_module_raises_clear_error():
    # Class 1 Multiturn (write=0): pyprofibus não suporta escravo só-leitura.
    with pytest.raises(GenericError, match="só-leitura"):
        make_generic_slave_desc(IFM, 9, ["Class 1 Multiturn"])


def test_generic_master_rm3007_class2_in_sim():
    # Config correta do RM3007: Class 2 Multiturn (0xF1) = lê 4 / escreve 4.
    m = GenericDpMaster(CONF, IFM, 9, ["Class 2 Multiturn"], sim=True)
    try:
        assert (m.input_size, m.output_size) == (4, 4)
        m.set_output(b"\x00\x00\x00\x00")
        m.poll()  # não deve lançar
    finally:
        m.close()
