import os
from pathlib import Path

import pytest

from pyprofibus import PbConf

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "config" / "amg11.conf"


@pytest.fixture
def in_project_root():
    old = os.getcwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(old)


def test_conf_loads_master_and_slave(in_project_root):
    conf = PbConf.fromFile(str(CONF))
    assert conf.dpMasterClass == 1
    assert conf.dpMasterAddr == 1
    assert conf.phyType == "serial"
    assert conf.phyBaud == 19200
    assert len(conf.slaveConfs) == 1

    slaveConf = conf.slaveConfs[0]
    assert slaveConf.addr == 3
    assert slaveConf.inputSize == 2
    assert slaveConf.outputSize == 2


def test_slave_desc_has_baumer_ident(in_project_root):
    conf = PbConf.fromFile(str(CONF))
    slaveDesc = conf.slaveConfs[0].makeDpSlaveDesc()
    assert slaveDesc.identNumber == 0x059B   # Baumer AMG/HMG/HEAG 13 bit
    assert slaveDesc.slaveAddr == 3


def test_class2_module_yields_cfg_elements(in_project_root):
    # O modulo Classe 2 (0xF0) deve produzir exatamente 1 elemento de config.
    conf = PbConf.fromFile(str(CONF))
    elems = conf.slaveConfs[0].gsd.getCfgDataElements()
    assert len(elems) == 1
    # DpCfgDataElement.identifier = primeiro byte de config do modulo (0xF0).
    assert elems[0].identifier == 0xF0
