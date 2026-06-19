#!/usr/bin/env python3
"""Sobe o dashboard web do mestre PROFIBUS AMG11."""

from __future__ import annotations

import argparse
from pathlib import Path

from profibus_amg11.config import load_config
from profibus_amg11.master import Amg11Master
from web.poller import EncoderPoller
from web.server import create_app

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8600)
    p.add_argument("--conf", default=str(ROOT / "config" / "amg11.conf"))
    p.add_argument("--encoder", default=str(ROOT / "config" / "encoder.yaml"))
    p.add_argument("--sim", action="store_true", help="PHY dummy (sem hardware)")
    args = p.parse_args(argv)

    cfg = load_config(args.encoder)
    source = Amg11Master(args.conf, cfg, sim=args.sim)
    poller = EncoderPoller(source, period=2 ** cfg.resolution_bits,
                           initial_offset=cfg.offset)
    poller.start()
    try:
        app = create_app(poller)
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        poller.stop()


if __name__ == "__main__":
    main()
