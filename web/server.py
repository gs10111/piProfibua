"""Transporte: Flask serve estáticos e um WebSocket com encoder + barramento."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, send_from_directory
from flask_sock import Sock

from web.snapshot import bus_snapshot_to_dict, snapshot_to_dict

STATIC_DIR = Path(__file__).resolve().parent / "static"


def handle_ws_message(controller, raw):
    """Despacha um comando do cliente. Mensagem inválida é ignorada."""
    try:
        data = json.loads(raw)
        cmd = data.get("cmd")
    except (ValueError, AttributeError):
        return
    if cmd == "zero":
        controller.zero()
    elif cmd == "clear_zero":
        controller.clear_zero()
    elif cmd == "scan":
        controller.scan()
    elif cmd == "apply_settings":
        try:
            controller.apply_settings(int(data["baud"]), int(data["master_addr"]))
        except (KeyError, TypeError, ValueError):
            return


def create_app(controller):
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")
    sock = Sock(app)

    @app.route("/")
    def index():
        return send_from_directory(str(STATIC_DIR), "index.html")

    @sock.route("/ws")
    def ws(ws):
        # Cada conexão recebe encoder + barramento (~15 Hz) e envia comandos.
        while True:
            try:
                ws.send(json.dumps(snapshot_to_dict(controller.encoder_snapshot())))
                ws.send(json.dumps(bus_snapshot_to_dict(controller.bus_snapshot())))
                msg = ws.receive(timeout=1 / 15)
            except Exception:
                break
            if msg is None:
                continue
            handle_ws_message(controller, msg)

    return app
