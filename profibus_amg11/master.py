"""Mestre PROFIBUS-DP (DPM1) para o encoder AMG 11, sobre pyprofibus."""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import replace
from pathlib import Path

from pyprofibus import PbConf

from profibus_amg11.encoder import decode


@contextlib.contextmanager
def _chdir(path):
    old = os.getcwd()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(old)


class Amg11Master:
    """Mestre de 1 escravo (o encoder) com loop de Data_Exchange.

    conf_path: caminho do .conf do pyprofibus (em config/, com gsd relativo a raiz).
    encoder_cfg: EncoderConfig (resolucao, sentido, offset, control_word).
    sim: se True, usa o PHY dummy (sem RS485) para rodar sem hardware.
    """

    def __init__(self, conf_path, encoder_cfg, sim=False, debug=False,
                 baud=None, master_addr=None):
        self.encoder_cfg = encoder_cfg
        self._out = bytearray(encoder_cfg.control_word.to_bytes(2, "big"))

        conf_path = Path(conf_path).resolve()
        project_root = conf_path.parent.parent  # config/ -> raiz
        with _chdir(project_root):
            conf = PbConf.fromFile(str(conf_path))
            if sim:
                conf.phyType = "dummyslave"
            if baud is not None:
                conf.phyBaud = baud
            if master_addr is not None:
                conf.dpMasterAddr = master_addr
            conf.debug = 2 if debug else 0
            self.master = conf.makeDPM()

        try:
            self.slave = conf.slaveConfs[0].makeDpSlaveDesc()
            self.master.addSlave(self.slave)
            self.master.initialize()
        except Exception:
            self.close()
            raise

    def poll(self):
        """Roda um passo da maquina de estados. Retorna EncoderReading ou None."""
        # Re-arma a palavra de saida a cada ciclo para sustentar o Data_Exchange.
        self.slave.setMasterOutData(bytearray(self._out))
        handled = self.master.run()
        if handled is self.slave:
            data = self.slave.getMasterInData()
            if data is not None:
                return decode(bytes(data), self.encoder_cfg)
        return None

    def set_offset(self, value):
        """Ajusta o offset por software (zero) reusando o decode existente (DRY)."""
        self.encoder_cfg = replace(self.encoder_cfg, offset=value)

    def read_once(self, timeout=5.0):
        """Bloqueia ate a primeira leitura valida ou estoura timeout (segundos)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reading = self.poll()
            if reading is not None:
                return reading
        raise TimeoutError("sem leitura do escravo em %.1fs" % timeout)

    def run(self, callback, hz=20.0):
        """Loop continuo: chama callback(EncoderReading) a cada leitura valida."""
        period = 1.0 / hz
        while True:
            start = time.monotonic()
            reading = self.poll()
            if reading is not None:
                callback(reading)
            slack = period - (time.monotonic() - start)
            if slack > 0:
                time.sleep(slack)

    def close(self):
        with contextlib.suppress(Exception):
            self.master.destroy()


def build_scan_phy(conf_path, baud, debug=False):
    """Cria uma PHY avulsa (no baud dado) para a varredura FDL.

    Reusa o mesmo .conf do mestre (chdir para resolver o GSD relativo). O
    chamador é dono do fechamento: chame phy.close() ao terminar.
    debug=True liga o trace de TX/RX da PHY (diagnóstico da varredura).
    """
    conf_path = Path(conf_path).resolve()
    project_root = conf_path.parent.parent
    with _chdir(project_root):
        conf = PbConf.fromFile(str(conf_path))
        conf.phyBaud = baud
        if debug:
            conf.debug = 2
        return conf.makePhy()
