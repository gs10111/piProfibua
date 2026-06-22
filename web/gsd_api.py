"""Rotas HTTP para gestão de GSD (CRUD), separadas do streaming WebSocket."""
from __future__ import annotations

from flask import jsonify, request

from profibus_amg11.gsd_info import (GsdInfoError, preview_params,
                                     preview_to_dict, summary_to_dict)


def _extract_upload(req):
    if "file" in req.files:
        f = req.files["file"]
        return (f.filename or "upload.gsd", f.read())
    if req.data:
        return (req.headers.get("X-Filename", "upload.gsd"), req.data)
    return (None, None)


def register_gsd_routes(app, store):
    @app.route("/api/gsd", methods=["GET"])
    def gsd_list():
        out = []
        for name in store.list():
            try:
                out.append(summary_to_dict(store.summary(name)))
            except (GsdInfoError, FileNotFoundError):
                out.append({"filename": name, "error": "parse"})
        return jsonify({"gsds": out})

    @app.route("/api/gsd", methods=["POST"])
    def gsd_upload():
        filename, data = _extract_upload(request)
        if data is None:
            return jsonify({"error": "sem arquivo"}), 400
        try:
            summary = store.save(filename, data)
        except FileExistsError:
            return jsonify({"error": "GSD com esse nome já existe"}), 409
        except GsdInfoError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(summary_to_dict(summary))

    @app.route("/api/gsd/<name>", methods=["GET"])
    def gsd_get(name):
        try:
            return jsonify(summary_to_dict(store.summary(name)))
        except FileNotFoundError:
            return jsonify({"error": "não encontrado"}), 404
        except GsdInfoError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/gsd/<name>/preview", methods=["POST"])
    def gsd_preview(name):
        try:
            data = store.read(name)
        except (FileNotFoundError, GsdInfoError):
            return jsonify({"error": "não encontrado"}), 404
        body = request.get_json(silent=True) or {}
        try:
            preview = preview_params(data, body.get("modules", []))
        except GsdInfoError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify(preview_to_dict(preview))
