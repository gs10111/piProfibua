#!/usr/bin/env python3
"""Sobe o app web: dashboard do encoder + explorador de barramento."""

from __future__ import annotations

import argparse
import configparser
from dataclasses import replace
from pathlib import Path

from pyprofibus.fdl import FdlTransceiver

from profibus_amg11.config import load_config
from profibus_amg11.master import Amg11Master, build_scan_phy
from profibus_amg11.scan import FdlBusProbe, SimBusProbe
from web.controller import BusController
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


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8600)
    p.add_argument("--conf", default=str(ROOT / "config" / "amg11.conf"))
    p.add_argument("--encoder", default=str(ROOT / "config" / "encoder.yaml"))
    p.add_argument("--sim", action="store_true", help="PHY dummy (sem hardware)")
    args = p.parse_args(argv)

    cfg = load_config(args.encoder)
    store = SettingsStore(ROOT / "config" / "bus.json")
    settings = store.load(default_settings_from_conf(args.conf))

    def make_exchange(s, offset):
        src = Amg11Master(args.conf, replace(cfg, offset=offset), sim=args.sim,
                          baud=s.baud, master_addr=s.master_addr)
        return EncoderPoller(src, period=2 ** cfg.resolution_bits,
                             initial_offset=offset)

    def make_probe(s):
        if args.sim:
            slave = default_slave_addr(args.conf)
            return SimBusProbe(found_addrs=[slave] if slave is not None else [])
        phy = build_scan_phy(args.conf, s.baud)
        return FdlBusProbe(FdlTransceiver(phy), master_addr=s.master_addr, phy=phy)

    controller = BusController(make_exchange, make_probe, settings,
                              initial_offset=cfg.offset,
                              on_settings_saved=store.save)
    controller.start()
    try:
        app = create_app(controller)
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
