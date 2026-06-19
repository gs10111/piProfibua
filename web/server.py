"""Transporte: Flask serve os estáticos e um WebSocket que publica o snapshot."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, send_from_directory
from flask_sock import Sock

from web.snapshot import snapshot_to_dict

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(poller):
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")
    sock = Sock(app)

    @app.route("/")
    def index():
        return send_from_directory(str(STATIC_DIR), "index.html")

    @sock.route("/ws")
    def ws(ws):
        # Cada conexão lê o snapshot compartilhado e empurra ~15 Hz;
        # entre envios, espera um comando do cliente (timeout curto).
        while True:
            try:
                ws.send(json.dumps(snapshot_to_dict(poller.snapshot())))
                msg = ws.receive(timeout=1 / 15)
            except Exception:
                break
            if msg is None:
                continue
            try:
                cmd = json.loads(msg).get("cmd")
            except (ValueError, AttributeError):
                continue
            if cmd == "zero":
                poller.zero()
            elif cmd == "clear_zero":
                poller.clear_zero()

    return app
