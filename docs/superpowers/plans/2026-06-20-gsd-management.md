# Gestão/Inspeção de GSD (B1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enviar `.gsd` por HTTP, guardar/listar/inspecionar, e pré-visualizar offline os bytes de parametrização (`Chk_Cfg`/`Set_Prm`) por escolha de módulo.

**Architecture:** Domínio puro `profibus_amg11/gsd_info.py` (wrap de `GsdInterp`) + app `web/gsd_store.py` (arquivos, validação, path-safety) + rotas HTTP `web/gsd_api.py` registradas em `create_app`. WebSocket de telemetria inalterado. Frontend ganha aba "GSD".

**Tech Stack:** Python 3.12, pyprofibus (`GsdInterp.fromBytes`), Flask, Preact+htm vendorizados, pytest.

## Global Constraints

- **Sem libs novas.** Flask já trata upload multipart. Frontend sem build.
- **Offline:** B1 não toca no barramento. Só parse + storage + preview puro.
- **`create_app` ganha parâmetro OPCIONAL `gsd_store=None`** — testes de A/v1 seguem verdes.
- **Path-safety:** nomes de GSD rejeitam separadores e `..`; só `[A-Za-z0-9._-]+.gsd`.
- **Fixtures de teste reais:** `gsd/PB13DPV0.gsd` (Baumer AMG11, ident 0x059B) e `gsd/IFM_0E75.gsd` (ifm, ident 0x0E75). Ambos versionados; uploads futuros ignorados pelo git.
- **Princípios de frontend v1/A:** dark, acento único, mono nos numerais, **sem emoji**, AA, foco visível, sem Inter default.
- Commits PT, terminando com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: gsd_info (domínio — parse + preview + serialização)

**Files:**
- Create: `profibus_amg11/gsd_info.py`
- Test: `tests/test_gsd_info.py`

**Interfaces:**
- Consumes: `pyprofibus.gsd.interp.GsdInterp`, `pyprofibus.gsd.parser.GsdError`.
- Produces: `GsdInfoError`; `ModuleInfo(name, config_hex, preset)`; `GsdSummary(filename, vendor, model, revision, ident, order, modular, dpv1, modules, max_tsdr)`; `ParamPreview(ident, modules, cfg_hex, user_prm_hex)`; `parse_gsd(data:bytes, filename:str)->GsdSummary`; `preview_params(data:bytes, module_names:list[str])->ParamPreview`; `summary_to_dict(s)->dict`; `preview_to_dict(p)->dict`; `module_to_dict(m)->dict`.

- [ ] **Step 1: Write the failing tests** (contra as 2 GSDs reais)

```python
# tests/test_gsd_info.py
from pathlib import Path

import pytest

from profibus_amg11.gsd_info import (GsdInfoError, parse_gsd, preview_params,
                                     summary_to_dict, preview_to_dict)

GSD = Path(__file__).resolve().parent.parent / "gsd"
AMG11 = (GSD / "PB13DPV0.gsd").read_bytes()
IFM = (GSD / "IFM_0E75.gsd").read_bytes()


def test_parse_amg11_metadata():
    s = parse_gsd(AMG11, "PB13DPV0.gsd")
    assert s.ident == 0x059B
    assert "Baumer" in s.vendor
    assert s.modular is True
    names = [m.name for m in s.modules]
    assert any("16 Bit Class 2" in n for n in names)
    assert s.max_tsdr[19200] == 60


def test_parse_ifm_metadata():
    s = parse_gsd(IFM, "IFM_0E75.gsd")
    assert s.ident == 0x0E75
    assert "ifm" in s.vendor.lower()
    assert len(s.modules) >= 6


def test_parse_invalid_raises():
    with pytest.raises(GsdInfoError):
        parse_gsd(b"isto nao e um gsd", "bad.gsd")


def test_preview_amg11_class2_module():
    p = preview_params(AMG11, ["16 Bit Class 2 Encoder "])
    assert p.ident == 0x059B
    assert p.cfg_hex == "f0"
    assert p.user_prm_hex.startswith("000a")


def test_preview_unknown_module_raises():
    with pytest.raises(GsdInfoError):
        preview_params(AMG11, ["modulo inexistente"])


def test_summary_to_dict_shape():
    d = summary_to_dict(parse_gsd(AMG11, "PB13DPV0.gsd"))
    assert d["ident_hex"] == "0x059B"
    assert d["filename"] == "PB13DPV0.gsd"
    assert isinstance(d["modules"], list)
    assert d["modules"][0].keys() >= {"name", "config_hex", "preset"}
    assert d["max_tsdr"]["19200"] == 60


def test_preview_to_dict_shape():
    d = preview_to_dict(preview_params(AMG11, ["16 Bit Class 2 Encoder "]))
    assert d["ident_hex"] == "0x059B" and d["cfg_hex"] == "f0"
    assert d["modules"] == ["16 Bit Class 2 Encoder "]
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_gsd_info.py -q` → FAIL (no module).

- [ ] **Step 3: Implement `profibus_amg11/gsd_info.py`**

```python
"""Inspeção de GSD e preview de parametrização (wrap de GsdInterp, puro)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from pyprofibus.gsd.interp import GsdInterp
from pyprofibus.gsd.parser import GsdError

BAUDS = (9600, 19200, 45450, 93750, 187500, 500000, 1500000)


class GsdInfoError(Exception):
    pass


@dataclass(frozen=True)
class ModuleInfo:
    name: str
    config_hex: str
    preset: bool


@dataclass(frozen=True)
class GsdSummary:
    filename: str
    vendor: str
    model: str
    revision: str
    ident: Optional[int]
    order: str
    modular: bool
    dpv1: bool
    modules: Tuple[ModuleInfo, ...]
    max_tsdr: dict


@dataclass(frozen=True)
class ParamPreview:
    ident: Optional[int]
    modules: Tuple[str, ...]
    cfg_hex: str
    user_prm_hex: str


def _interp(data, filename):
    try:
        return GsdInterp.fromBytes(bytes(data), filename=filename)
    except GsdError as e:
        raise GsdInfoError(str(e))
    except Exception as e:
        raise GsdInfoError("GSD inválido: %s" % e)


def _module_config_hex(mod):
    cb = getattr(mod, "configBytes", b"") or b""
    return bytes(cb).hex()


def parse_gsd(data, filename) -> GsdSummary:
    g = _interp(data, filename)
    mods = tuple(
        ModuleInfo(name=m.name, config_hex=_module_config_hex(m),
                   preset=bool(m.getField("Preset", False)))
        for m in g.getField("Module", [])
    )
    tsdr = {}
    for b in BAUDS:
        try:
            tsdr[b] = g.getMaxTSDR(b)
        except GsdError:
            tsdr[b] = None
    return GsdSummary(
        filename=filename,
        vendor=g.getField("Vendor_Name", "") or "",
        model=g.getField("Model_Name", "") or "",
        revision=str(g.getField("Revision", "") or ""),
        ident=g.getField("Ident_Number"),
        order=str(g.getField("OrderNumber", "") or ""),
        modular=bool(g.isModular()),
        dpv1=bool(g.isDPV1()),
        modules=mods,
        max_tsdr=tsdr,
    )


def preview_params(data, module_names) -> ParamPreview:
    g = _interp(data, "<preview>")
    chosen = list(module_names or [])
    if chosen:
        g.clearConfiguredModules()
        for name in chosen:
            try:
                g.setConfiguredModule(name)
            except GsdError as e:
                raise GsdInfoError(str(e))
    try:
        cfg = bytearray()
        for e in g.getCfgDataElements():
            cfg += bytes(e.getDU())
        prm = g.getUserPrmData()
        ident = g.getIdentNumber()
    except GsdError as e:
        raise GsdInfoError(str(e))
    return ParamPreview(ident=ident, modules=tuple(chosen),
                        cfg_hex=bytes(cfg).hex(), user_prm_hex=bytes(prm).hex())


def _ident_hex(ident):
    return ("0x%04X" % ident) if ident is not None else None


def module_to_dict(m):
    return {"name": m.name, "config_hex": m.config_hex, "preset": m.preset}


def summary_to_dict(s):
    return {
        "filename": s.filename, "vendor": s.vendor, "model": s.model,
        "revision": s.revision, "ident": s.ident, "ident_hex": _ident_hex(s.ident),
        "order": s.order, "modular": s.modular, "dpv1": s.dpv1,
        "modules": [module_to_dict(m) for m in s.modules],
        "max_tsdr": {str(k): v for k, v in s.max_tsdr.items()},
    }


def preview_to_dict(p):
    return {
        "ident": p.ident, "ident_hex": _ident_hex(p.ident),
        "modules": list(p.modules), "cfg_hex": p.cfg_hex,
        "user_prm_hex": p.user_prm_hex,
    }
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/test_gsd_info.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add profibus_amg11/gsd_info.py tests/test_gsd_info.py && git commit -m "feat: gsd_info - parse e preview de GSD (domínio puro)"`

---

### Task 2: GsdStore (armazenamento + validação + path-safety)

**Files:**
- Create: `web/gsd_store.py`
- Test: `tests/test_gsd_store.py`

**Interfaces:**
- Consumes: `profibus_amg11.gsd_info` (`parse_gsd`, `GsdInfoError`).
- Produces: `GsdStore(directory)` com `list()->list[str]`, `save(filename, data)->GsdSummary`, `read(name)->bytes`, `summary(name)->GsdSummary`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gsd_store.py
from pathlib import Path

import pytest

from profibus_amg11.gsd_info import GsdInfoError
from web.gsd_store import GsdStore

AMG11 = (Path(__file__).resolve().parent.parent / "gsd" / "PB13DPV0.gsd").read_bytes()


def test_save_validates_and_writes(tmp_path):
    store = GsdStore(tmp_path)
    s = store.save("enc.gsd", AMG11)
    assert s.ident == 0x059B
    assert (tmp_path / "enc.gsd").exists()
    assert store.list() == ["enc.gsd"]


def test_save_rejects_garbage(tmp_path):
    store = GsdStore(tmp_path)
    with pytest.raises(GsdInfoError):
        store.save("bad.gsd", b"nao e gsd")
    assert store.list() == []


def test_save_rejects_unsafe_name(tmp_path):
    store = GsdStore(tmp_path)
    for bad in ("../evil.gsd", "a/b.gsd", "x.txt", "..gsd/.."):
        with pytest.raises(GsdInfoError):
            store.save(bad, AMG11)


def test_read_roundtrip_and_missing(tmp_path):
    store = GsdStore(tmp_path)
    store.save("enc.gsd", AMG11)
    assert store.read("enc.gsd") == AMG11
    with pytest.raises(FileNotFoundError):
        store.read("nope.gsd")


def test_list_only_gsd(tmp_path):
    (tmp_path / "note.txt").write_text("x")
    store = GsdStore(tmp_path)
    store.save("enc.gsd", AMG11)
    assert store.list() == ["enc.gsd"]
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_gsd_store.py -q` → FAIL.

- [ ] **Step 3: Implement `web/gsd_store.py`**

```python
"""Armazenamento de arquivos GSD com validação e segurança de caminho."""
from __future__ import annotations

import re
from pathlib import Path

from profibus_amg11.gsd_info import GsdInfoError, parse_gsd

_SAFE = re.compile(r"^[A-Za-z0-9._-]+\.gsd$", re.IGNORECASE)


class GsdStore:
    def __init__(self, directory):
        self._dir = Path(directory)

    def _safe(self, name):
        if "/" in name or "\\" in name or ".." in name or not _SAFE.match(name):
            raise GsdInfoError("nome de GSD inseguro: %r" % name)
        return name

    def list(self):
        if not self._dir.exists():
            return []
        return sorted(p.name for p in self._dir.glob("*.gsd"))

    def save(self, filename, data):
        name = self._safe(filename)
        summary = parse_gsd(data, name)        # valida; levanta GsdInfoError
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / name).write_bytes(bytes(data))
        return summary

    def read(self, name):
        path = self._dir / self._safe(name)
        if not path.exists():
            raise FileNotFoundError(name)
        return path.read_bytes()

    def summary(self, name):
        return parse_gsd(self.read(name), self._safe(name))
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/test_gsd_store.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add web/gsd_store.py tests/test_gsd_store.py && git commit -m "feat: GsdStore - upload/list/read com validação e path-safety"`

---

### Task 3: Rotas HTTP de GSD + wiring em create_app

**Files:**
- Create: `web/gsd_api.py`
- Modify: `web/server.py` (assinatura `create_app(controller, gsd_store=None)` + registro)
- Test: `tests/test_gsd_api.py`

**Interfaces:**
- Consumes: `GsdStore`; `profibus_amg11.gsd_info` (`preview_params`, `summary_to_dict`, `preview_to_dict`, `GsdInfoError`).
- Produces: `register_gsd_routes(app, store)`; rotas `GET/POST /api/gsd`, `GET /api/gsd/<name>`, `POST /api/gsd/<name>/preview`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gsd_api.py
import io
import json
from pathlib import Path

from web.gsd_store import GsdStore
from web.server import create_app
from web.scanner import BusSnapshot, ScanState
from web.settings import BusSettings
from web.snapshot import initial_snapshot

AMG11 = (Path(__file__).resolve().parent.parent / "gsd" / "PB13DPV0.gsd").read_bytes()


class FakeController:
    def encoder_snapshot(self): return initial_snapshot()
    def bus_snapshot(self): return BusSnapshot("exchange", BusSettings(), ScanState(), "ok")
    def zero(self): pass
    def clear_zero(self): pass
    def scan(self): pass
    def apply_settings(self, b, m): pass


def make_client(tmp_path):
    app = create_app(FakeController(), gsd_store=GsdStore(tmp_path))
    return app.test_client()


def test_upload_and_list(tmp_path):
    c = make_client(tmp_path)
    r = c.post("/api/gsd", data={"file": (io.BytesIO(AMG11), "enc.gsd")},
               content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["ident_hex"] == "0x059B"
    r = c.get("/api/gsd")
    assert [g["filename"] for g in r.get_json()["gsds"]] == ["enc.gsd"]


def test_upload_invalid_returns_400(tmp_path):
    c = make_client(tmp_path)
    r = c.post("/api/gsd", data={"file": (io.BytesIO(b"lixo"), "bad.gsd")},
               content_type="multipart/form-data")
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_get_one_and_missing(tmp_path):
    c = make_client(tmp_path)
    c.post("/api/gsd", data={"file": (io.BytesIO(AMG11), "enc.gsd")},
           content_type="multipart/form-data")
    assert c.get("/api/gsd/enc.gsd").get_json()["ident_hex"] == "0x059B"
    assert c.get("/api/gsd/nope.gsd").status_code == 404


def test_preview_endpoint(tmp_path):
    c = make_client(tmp_path)
    c.post("/api/gsd", data={"file": (io.BytesIO(AMG11), "enc.gsd")},
           content_type="multipart/form-data")
    r = c.post("/api/gsd/enc.gsd/preview",
               data=json.dumps({"modules": ["16 Bit Class 2 Encoder "]}),
               content_type="application/json")
    assert r.status_code == 200
    assert r.get_json()["cfg_hex"] == "f0"


def test_gsd_routes_absent_without_store(tmp_path):
    app = create_app(FakeController())          # sem gsd_store
    assert app.test_client().get("/api/gsd").status_code == 404
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_gsd_api.py -q` → FAIL.

- [ ] **Step 3: Implement `web/gsd_api.py`**

```python
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
```

- [ ] **Step 4: Modify `web/server.py`** — assinatura + registro condicional:

```python
def create_app(controller, gsd_store=None):
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")
    sock = Sock(app)

    @app.route("/")
    def index():
        return send_from_directory(str(STATIC_DIR), "index.html")

    @sock.route("/ws")
    def ws(ws):
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

    if gsd_store is not None:
        from web.gsd_api import register_gsd_routes
        register_gsd_routes(app, gsd_store)

    return app
```

- [ ] **Step 5: Run to verify pass + full suite** — `.venv/bin/python -m pytest tests/test_gsd_api.py tests/test_server.py -q` → PASS.

- [ ] **Step 6: Commit** — `git add web/gsd_api.py web/server.py tests/test_gsd_api.py && git commit -m "feat: rotas HTTP de GSD (upload/list/get/preview) + wiring em create_app"`

---

### Task 4: serve.py wiring + .gitignore + fixture

**Files:**
- Modify: `serve.py` (monta `GsdStore`, passa a `create_app`)
- Modify: `.gitignore` (ignora uploads, mantém fixtures)
- Track: `gsd/IFM_0E75.gsd` (fixture de teste)

- [ ] **Step 1: Modify `serve.py`** — importar e montar o store:

Adicionar ao topo: `from web.gsd_store import GsdStore`. Em `main`, trocar a criação do app:
```python
    gsd_store = GsdStore(ROOT / "gsd")
    controller.start()
    try:
        app = create_app(controller, gsd_store=gsd_store)
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        controller.stop()
```

- [ ] **Step 2: Modify `.gitignore`** — adicionar:
```
gsd/*.gsd
!gsd/PB13DPV0.gsd
!gsd/IFM_0E75.gsd
```

- [ ] **Step 3: Track the IFM fixture** — `git add -f gsd/IFM_0E75.gsd` (a negação no .gitignore já permite; `-f` por garantia).

- [ ] **Step 4: Smoke test em sim** — `.venv/bin/python serve.py --sim --port 8697 &` ; `curl -s --retry 30 --retry-connrefused localhost:8697/api/gsd` deve retornar `{"gsds":[...]}` com PB13DPV0 e IFM; matar o processo.

- [ ] **Step 5: Run full suite** — `.venv/bin/python -m pytest -q` → todos verdes.

- [ ] **Step 6: Commit** — `git add serve.py .gitignore gsd/IFM_0E75.gsd && git commit -m "feat: wiring do GsdStore no serve.py + fixtures/gitignore de GSD"`

---

### Task 5: Frontend — aba GSD (upload, lista, inspetor, preview)

**Files:**
- Modify: `web/static/app.js` (componente `GsdView` + terceira aba)
- Modify: `web/static/styles.css` (estilos da aba GSD)
- Test: `tests/test_frontend_assets.py` (asserções da aba GSD)

- [ ] **Step 1: Write the failing tests** (asserções no fonte)

```python
# tests/test_frontend_assets.py  (acrescentar)
def test_app_has_gsd_tab_and_upload():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "GSD" in js
    assert "/api/gsd" in js
    assert "FormData" in js


def test_gsd_preview_shows_cfg_and_prm():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "cfg_hex" in js and "user_prm_hex" in js
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_frontend_assets.py -q` → FAIL.

- [ ] **Step 3: Add `GsdView` to `web/static/app.js`** (antes de `function App()`):

```javascript
function GsdView() {
  const [list, setList] = useState([]);
  const [sel, setSel] = useState(null);
  const [chosen, setChosen] = useState([]);
  const [preview, setPreview] = useState(null);
  const [err, setErr] = useState("");
  const refresh = () => fetch("/api/gsd").then((r) => r.json())
    .then((d) => setList(d.gsds || [])).catch(() => {});
  useEffect(() => { refresh(); }, []);
  const open = (name) => fetch(`/api/gsd/${name}`).then((r) => r.json())
    .then((d) => { setSel(d); setChosen([]); setPreview(null); });
  const runPreview = (mods) => fetch(`/api/gsd/${sel.filename}/preview`,
    { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modules: mods }) })
    .then((r) => r.json()).then(setPreview).catch(() => {});
  const toggle = (name) => {
    const next = chosen.includes(name) ? chosen.filter((x) => x !== name) : [...chosen, name];
    setChosen(next);
    if (sel) runPreview(next);
  };
  const upload = (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    setErr("");
    fetch("/api/gsd", { method: "POST", body: fd }).then(async (r) => {
      const d = await r.json();
      if (!r.ok) { setErr(d.error || "falha no upload"); return; }
      refresh();
      open(d.filename);
    }).catch(() => setErr("falha de rede"));
  };
  return html`
    <div class="view gsd">
      <div class="controls">
        <label>Enviar GSD
          <input type="file" accept=".gsd"
                 onChange=${(e) => upload(e.target.files[0])} />
        </label>
      </div>
      ${err ? html`<p class="warn">${err}</p>` : ""}
      <table class="stations">
        <thead><tr><th>Arquivo</th><th>Modelo</th><th>Ident</th></tr></thead>
        <tbody>
          ${list.map((g) => html`<tr class="clickable" onClick=${() => open(g.filename)}>
            <td>${g.filename}</td><td>${g.model || "--"}</td><td>${g.ident_hex || "--"}</td></tr>`)}
        </tbody>
      </table>
      ${list.length === 0 ? html`<p class="muted">Nenhum GSD enviado ainda.</p>` : ""}
      ${sel ? html`
        <div class="inspector">
          <div class="rows">
            <div>fabricante <b>${sel.vendor}</b></div>
            <div>modelo <b>${sel.model}</b></div>
            <div>ident <b>${sel.ident_hex}</b></div>
            <div>tipo <b>${sel.modular ? "modular" : "compacto"}${sel.dpv1 ? " · DPV1" : ""}</b></div>
          </div>
          <div class="muted">Módulos (escolha para ver a parametrização):</div>
          <div class="modlist">
            ${(sel.modules || []).filter((m) => !m.preset).map((m) => html`
              <label class="mod"><input type="checkbox" checked=${chosen.includes(m.name)}
                onChange=${() => toggle(m.name)} /> ${m.name}</label>`)}
          </div>
          ${preview ? html`
            <div class="rows">
              <div>ident <b>${preview.ident_hex}</b></div>
              <div>cfg (Chk_Cfg) <b>${preview.cfg_hex || "--"}</b></div>
              <div>user_prm (Set_Prm) <b>${preview.user_prm_hex || "--"}</b></div>
            </div>` : ""}
        </div>` : ""}
    </div>`;
}
```

- [ ] **Step 4: Wire the third tab in `App()`** — adicionar o botão e o ramo:

```javascript
function App() {
  const { encoder, bus, send } = useBusSocket();
  const [tab, setTab] = useState("encoder");
  const view = tab === "encoder"
    ? html`<${EncoderView} snap=${encoder} send=${send} />`
    : tab === "bus"
      ? html`<${BusView} bus=${bus} send=${send} />`
      : html`<${GsdView} />`;
  return html`
    <div class="panel">
      <nav class="tabs">
        <button class=${"tab" + (tab === "encoder" ? " active" : "")}
                onClick=${() => setTab("encoder")}>Encoder</button>
        <button class=${"tab" + (tab === "bus" ? " active" : "")}
                onClick=${() => setTab("bus")}>Barramento</button>
        <button class=${"tab" + (tab === "gsd" ? " active" : "")}
                onClick=${() => setTab("gsd")}>GSD</button>
      </nav>
      ${view}
    </div>`;
}
```

- [ ] **Step 5: Add CSS to `web/static/styles.css`**:

```css
/* aba GSD */
.gsd .inspector{display:flex;flex-direction:column;gap:12px;
  border-top:1px solid var(--hair);padding-top:14px}
.stations tr.clickable{cursor:pointer}
.stations tr.clickable:hover td{color:var(--ink)}
.modlist{display:flex;flex-direction:column;gap:6px}
.mod{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink-dim);
  font-family:var(--mono)}
.gsd input[type=file]{color:var(--ink-dim);font-family:var(--mono);font-size:12px}
```

- [ ] **Step 6: Run static asserts + full suite** — `.venv/bin/python -m pytest -q` → todos verdes.

- [ ] **Step 7: Smoke visual em sim** — subir `serve.py --sim`, abrir, aba GSD: lista mostra PB13DPV0 e IFM; clicar, escolher "16 Bit Class 2 Encoder", ver cfg `f0` e user_prm no preview. Matar.

- [ ] **Step 8: Commit** — `git add web/static/app.js web/static/styles.css tests/test_frontend_assets.py && git commit -m "feat: aba GSD no frontend (upload, lista, inspetor, preview de parametrização)"`

---

## Self-Review

**1. Spec coverage:**
- §2 upload HTTP → Tasks 3+4. listagem → Task 3. inspeção → Tasks 1+3. preview dry-run → Tasks 1+3. aba GSD → Task 5. ✓
- §3 GsdInterp.fromBytes/getField/preview → Task 1 (aterrado nas 2 GSDs). ✓
- §4 camadas (gsd_info domínio / gsd_store app / gsd_api rotas / server wiring) → Tasks 1-3. ✓
- §5 contrato HTTP (GET/POST/GET<name>/POST preview + shapes) → Tasks 1 (to_dict) + 3. ✓
- §6 frontend → Task 5. §7 erros (400/404, nada salvo) → Tasks 2+3 tests. ✓
- §8 testes → cada task. §10 gitignore/fixtures → Task 4. ✓

**2. Placeholder scan:** sem TBD/TODO; todo passo tem código real. ✓

**3. Type consistency:** `GsdSummary`/`ModuleInfo`/`ParamPreview` e `parse_gsd`/`preview_params`/`*_to_dict` consistentes entre gsd_info/gsd_store/gsd_api/testes. `create_app(controller, gsd_store=None)` consistente em server/serve/tests. ✓
