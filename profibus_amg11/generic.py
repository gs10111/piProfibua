"""Mestre DP genérico: parametriza um escravo de um GSD em memória e troca I/O cru."""
from __future__ import annotations

import contextlib
from pathlib import Path

from pyprofibus import PbConf
from pyprofibus.gsd.interp import GsdInterp
from pyprofibus.gsd.parser import GsdError

from profibus_amg11.master import _chdir


class GenericError(Exception):
    pass


class _GenericSlaveConf:
    """slaveConf leve com os atributos que o DpSlaveDesc lê."""

    def __init__(self, gsd, addr, input_size, output_size):
        self.gsd = gsd
        self.addr = addr
        self.name = "generic-%d" % addr
        self.index = 1
        self.inputSize = input_size
        self.outputSize = output_size
        self.diagPeriod = 0
        self.syncMode = False
        self.freezeMode = False
        self.groupMask = 1
        self.watchdogMs = 1000


def make_generic_slave_desc(gsd_bytes, address, modules, input_size, output_size):
    """Monta um DpSlaveDesc de um GSD (bytes) + módulos + endereço + tamanhos."""
    from pyprofibus.dp_master import DpSlaveDesc
    try:
        gsd = GsdInterp.fromBytes(bytes(gsd_bytes), filename="<generic>")
        chosen = list(modules or [])
        if chosen:
            gsd.clearConfiguredModules()
            for name in chosen:
                gsd.setConfiguredModule(name)
        conf = _GenericSlaveConf(gsd, address, input_size, output_size)
        desc = DpSlaveDesc(conf)
        desc.setCfgDataElements(gsd.getCfgDataElements())
        desc.setUserPrmData(gsd.getUserPrmData())
        desc.setSyncMode(conf.syncMode)
        desc.setFreezeMode(conf.freezeMode)
        desc.setGroupMask(conf.groupMask)
        desc.setWatchdog(conf.watchdogMs)
        return desc
    except GsdError as e:
        raise GenericError(str(e))


class GenericDpMaster:
    """DPM1 de um escravo genérico; troca DX e expõe I/O cru. (GenericSource)"""

    def __init__(self, conf_path, gsd_bytes, address, modules,
                 input_size, output_size, baud=None, master_addr=None,
                 sim=False, debug=False):
        self._out = bytearray(output_size)
        conf_path = Path(conf_path).resolve()
        project_root = conf_path.parent.parent
        with _chdir(project_root):
            conf = PbConf.fromFile(str(conf_path))
            if sim:
                conf.phyType = "dummyslave"
            if baud is not None:
                conf.phyBaud = baud
            if master_addr is not None:
                conf.dpMasterAddr = master_addr
            conf.debug = 2 if debug else 0
            phy = conf.makePhy()                  # sim: echoDXSize vem dos slaveConfs do .conf
            self.master = conf.makeDPM(phy=phy)   # mestre sem escravos
        try:
            self.slave = make_generic_slave_desc(gsd_bytes, address, modules,
                                                 input_size, output_size)
            self.master.addSlave(self.slave)
            self.master.initialize()
        except Exception:
            self.close()
            raise

    def poll(self):
        self.slave.setMasterOutData(bytearray(self._out))
        handled = self.master.run()
        if handled is self.slave:
            data = self.slave.getMasterInData()
            if data is not None:
                return bytes(data)
        return None

    def set_output(self, data):
        self._out = bytearray(data)

    @property
    def connected(self):
        try:
            return bool(self.slave.isConnected())
        except Exception:
            return False

    @property
    def diag(self):
        return "OK" if self.connected else "conectando"

    def close(self):
        with contextlib.suppress(Exception):
            self.master.destroy()
