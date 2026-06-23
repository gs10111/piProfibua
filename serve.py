#!/usr/bin/env python3
"""Sobe o app web: dashboard do encoder + explorador de barramento."""

from __future__ import annotations

import argparse
import configparser
from dataclasses import replace
from pathlib import Path

from pyprofibus.fdl import FdlTransceiver

from profibus_amg11.config import load_config
from profibus_amg11.generic import GenericDpMaster
from profibus_amg11.master import Amg11Master, build_scan_phy
from profibus_amg11.scan import FdlBusProbe, SimBusProbe
from web.controller import BusController
from web.generic_poller import GenericPoller
from web.gsd_store import GsdStore
from web.poller import EncoderPoller
from web.server import create_app
from web.settings import ALLOWED_BAUDS, BusSettings, SettingsStore

ROOT = Path(__file__).resolve().parent


def default_settings_from_conf(conf_path) -> BusSettings:
    """Lê baud + endereço do mestre do .conf (sem carregar GSD) como default."""
    cp = configparser.ConfigParser()
    cp.read(conf_path)
    baud = cp.getint("PHY", "baud", fallback=19200)
    master = cp.getint("DP", "master_addr", fallback=1)
    if baud not in ALLOWED_BAUDS:
        baud = 19200
    if not (1 <= master <= 126):
        master = 1
    return BusSettings(baud=baud, master_addr=master)


def default_slave_addr(conf_path):
    """Primeiro endereço de escravo do .conf (para a probe simulada de --sim)."""
    cp = configparser.ConfigParser()
    cp.read(conf_path)
    for sec in cp.sections():
        if sec.startswith("SLAVE_"):
            try:
                return cp.getint(sec, "addr")
            except (configparser.NoOptionError, ValueError):
                pass
    return None


def build_controller(conf_path, encoder_path, sim=False, bus_json=None,
                     addresses=None, gsd_dir=None):
    """Monta o BusController com as factories de produção (ou simuladas)."""
    cfg = load_config(encoder_path)
    store = SettingsStore(bus_json or (ROOT / "config" / "bus.json"))
    settings = store.load(default_settings_from_conf(conf_path))
    gsd_store = GsdStore(gsd_dir or (ROOT / "gsd"))

    def make_exchange(s, offset):
        src = Amg11Master(conf_path, replace(cfg, offset=offset), sim=sim,
                          baud=s.baud, master_addr=s.master_addr)
        return EncoderPoller(src, period=2 ** cfg.resolution_bits,
                             initial_offset=offset)

    def make_probe(s):
        if sim:
            slave = default_slave_addr(conf_path)
            return SimBusProbe(found_addrs=[slave] if slave is not None else [])
        phy = build_scan_phy(conf_path, s.baud)
        return FdlBusProbe(FdlTransceiver(phy), master_addr=s.master_addr, phy=phy)

    def make_generic(s, spec):
        data = gsd_store.read(spec.gsd)   # FileNotFoundError/GsdInfoError -> idle no controller
        src = GenericDpMaster(conf_path, data, spec.address, list(spec.modules),
                              baud=s.baud, master_addr=s.master_addr, sim=sim)
        # tamanhos derivados do GSD (mestre lê=input_size, escreve=output_size)
        return GenericPoller(src, spec.address, src.input_size, src.output_size)

    return BusController(make_exchange, make_probe, settings,
                         initial_offset=cfg.offset, addresses=addresses,
                         on_settings_saved=store.save, make_generic=make_generic)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8600)
    p.add_argument("--conf", default=str(ROOT / "config" / "amg11.conf"))
    p.add_argument("--encoder", default=str(ROOT / "config" / "encoder.yaml"))
    p.add_argument("--sim", action="store_true", help="PHY dummy (sem hardware)")
    args = p.parse_args(argv)

    controller = build_controller(args.conf, args.encoder, sim=args.sim)
    gsd_store = GsdStore(ROOT / "gsd")
    controller.start()
    try:
        app = create_app(controller, gsd_store=gsd_store)
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
