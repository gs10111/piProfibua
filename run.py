#!/usr/bin/env python3
"""CLI do mestre PROFIBUS-DP para o encoder Baumer AMG 11."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from profibus_amg11.config import load_config
from profibus_amg11.master import Amg11Master

ROOT = Path(__file__).resolve().parent


def _conf_baud_addr(conf_path):
    """Lê baud do [PHY] e endereço do [DP] do .conf (sem carregar GSD)."""
    import configparser
    cp = configparser.ConfigParser()
    cp.read(conf_path)
    return (cp.getint("PHY", "baud", fallback=19200),
            cp.getint("DP", "master_addr", fallback=1))


def _slave_addrs(conf_path):
    import configparser
    cp = configparser.ConfigParser()
    cp.read(conf_path)
    out = []
    for sec in cp.sections():
        if sec.startswith("SLAVE_"):
            try:
                out.append(cp.getint(sec, "addr"))
            except (configparser.NoOptionError, ValueError):
                pass
    return out


def scan_bus(args, log):
    """Varredura de barramento (live list FDL) pelo terminal — independe da web."""
    from profibus_amg11.scan import FdlBusProbe, SimBusProbe

    baud_conf, master_addr = _conf_baud_addr(args.conf)
    baud = args.baud or baud_conf

    if args.sim:
        probe, phy = SimBusProbe(found_addrs=_slave_addrs(args.conf)), None
    else:
        from pyprofibus.fdl import FdlTransceiver
        from profibus_amg11.master import build_scan_phy
        phy = build_scan_phy(args.conf, baud)
        probe = FdlBusProbe(FdlTransceiver(phy), master_addr=master_addr,
                            timeout=args.scan_timeout, phy=phy)

    log.info("varrendo 0..126  (baud=%d, mestre=%d, timeout=%.0fms, tentativas=%d)",
             baud, master_addr, args.scan_timeout * 1000, args.retries)
    found = []
    try:
        for addr in range(0, 127):
            if addr == master_addr:
                continue
            station = None
            for _ in range(max(1, args.retries)):
                station = probe.probe(addr)
                if station:
                    break
            if station:
                found.append(station)
                log.info("  achou  addr=%-3d  tipo=%-16s  %.1f ms",
                         station.addr, station.station_type.value, station.response_ms)
    finally:
        try:
            probe.close()
        except Exception:
            pass

    if found:
        log.info("total: %d estacao(oes) no barramento.", len(found))
    else:
        log.info("nenhuma estacao respondeu (ver wiring/baud/endereco).")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--conf", default=str(ROOT / "config" / "amg11.conf"),
                   help="arquivo .conf do pyprofibus")
    p.add_argument("--encoder", default=str(ROOT / "config" / "encoder.yaml"),
                   help="arquivo encoder.yaml")
    p.add_argument("--sim", action="store_true",
                   help="usa o PHY dummy (sem hardware RS485)")
    p.add_argument("--scan", action="store_true",
                   help="varre o barramento (live list FDL) e sai")
    p.add_argument("--baud", type=int, default=None,
                   help="baud para a varredura (default: o do .conf)")
    p.add_argument("--scan-timeout", type=float, default=0.1,
                   help="timeout por endereco na varredura (s)")
    p.add_argument("--retries", type=int, default=2,
                   help="tentativas por endereco na varredura")
    p.add_argument("--once", action="store_true",
                   help="le uma vez e sai")
    p.add_argument("--hz", type=float, default=20.0,
                   help="taxa de leitura no modo continuo")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="loga o debug do pyprofibus")
    args = p.parse_args(argv)

    if args.hz <= 0:
        p.error("--hz deve ser maior que zero")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("amg11")

    if args.scan:
        return scan_bus(args, log)

    cfg = load_config(args.encoder)
    master = Amg11Master(args.conf, cfg, sim=args.sim, debug=args.verbose)

    if args.once:
        try:
            r = master.read_once()
            log.info("raw=%d  angle=%.3f deg  bytes=%s", r.raw, r.angle_deg, r.bytes_hex)
        finally:
            master.close()
        return 0

    def on_reading(r):
        log.info("raw=%5d  angle=%7.3f deg", r.raw, r.angle_deg)

    try:
        master.run(on_reading, hz=args.hz)
    except KeyboardInterrupt:
        log.info("encerrando")
    finally:
        master.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
