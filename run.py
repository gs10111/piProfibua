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


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--conf", default=str(ROOT / "config" / "amg11.conf"),
                   help="arquivo .conf do pyprofibus")
    p.add_argument("--encoder", default=str(ROOT / "config" / "encoder.yaml"),
                   help="arquivo encoder.yaml")
    p.add_argument("--sim", action="store_true",
                   help="usa o PHY dummy (sem hardware RS485)")
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
