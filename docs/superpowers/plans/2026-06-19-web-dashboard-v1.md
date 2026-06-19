# Dashboard web v1 — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Task 6 é uma revisão final obrigatória com a skill `code-review`.**

**Goal:** Servir a leitura do encoder (que já funciona no Pi3) num dashboard web em tempo real (ângulo/raw/bytes/estado/diagnóstico/taxa) com um botão "zerar aqui", em cima da biblioteca existente.

**Architecture:** Camadas SOLID — `ReadingSource` (Protocol) ← `Amg11Master`/`FakeSource`; `EncoderPoller` (thread de fundo dona da serial, mantém um `Snapshot`); `web/server.py` (Flask + flask-sock) só transporta; frontend Preact sem build, vendorizado.

**Tech Stack:** Python, pyprofibus, Flask, flask-sock; frontend Preact + htm (ESM vendorizado), CSS autoral, fontes woff2 vendorizadas. Sem npm/Node.

**Referência:** `docs/superpowers/specs/2026-06-19-web-dashboard-v1-design.md`

## Global Constraints

- Trabalhar de `/home/ubuntu/repos/pi5-profibus-amg11`; ativar venv antes de python/pytest: `. .venv/bin/activate`.
- Os **23 testes atuais** devem continuar verdes ao fim de cada task (`pytest -q`).
- A lib `profibus_amg11/` não muda, exceto adicionar `Amg11Master.set_offset(int)` e o novo `profibus_amg11/source.py`.
- Frontend **sem build**: Preact + htm + fontes **vendorizados** (arquivos locais em `web/static/vendor/`). Sem npm/Node, sem CDN em runtime.
- Frontend: **Inter banido como default**; **um** acento contido (sem roxo-de-IA, sem gradiente genérico); **sem emoji** na UI; contraste WCAG AA; respeitar `prefers-reduced-motion`; tema dark travado.
- Porta padrão **8600** (configurável em `serve.py`).
- pytest usa `pythonpath=["."]` (já no `pyproject.toml`) → `import web.*`, `import profibus_amg11.*` e (nos testes) `from fakes import FakeSource` funcionam.

---

## Task 1: `ReadingSource` (Protocol) + `Amg11Master.set_offset` + `FakeSource`

**Files:**
- Create: `profibus_amg11/source.py`
- Modify: `profibus_amg11/master.py` (adicionar `set_offset`)
- Create: `tests/fakes.py`
- Test: `tests/test_source_fake.py`

**Interfaces:**
- Produces:
  - `ReadingSource` (typing.Protocol): `poll() -> EncoderReading | None`, `set_offset(value: int) -> None`, `close() -> None`.
  - `Amg11Master.set_offset(value: int) -> None`.
  - `FakeSource(raw16_seq: list[int | None], bits: int = 13)` implementando `ReadingSource`; emite as leituras da sequência ciclicamente (`None` → `poll()` retorna `None`); `set_offset` muda a decodificação; `close()` seta `.closed = True`.
- Consumes: `EncoderReading`, `decode`, `EncoderConfig` (já existentes).

- [ ] **Step 1: Escrever o teste que falha** — `tests/test_source_fake.py`:
```python
from profibus_amg11.config import EncoderConfig
from profibus_amg11.master import Amg11Master
from profibus_amg11.source import ReadingSource
from fakes import FakeSource


def test_fakesource_conforms_and_emits():
    src = FakeSource([0x0800, 0x1000])  # 90°, 180°
    assert isinstance(src, ReadingSource)  # Protocol runtime check
    assert src.poll().raw == 0x0800
    assert src.poll().raw == 0x1000
    assert src.poll().raw == 0x0800       # cicla


def test_fakesource_none_entry_returns_none():
    src = FakeSource([0x0800, None])
    assert src.poll().raw == 0x0800
    assert src.poll() is None


def test_fakesource_set_offset_changes_decode():
    src = FakeSource([0x0800])            # raw bruto 2048
    src.set_offset(0x0800)               # zera nesse ponto
    assert src.poll().raw == 0           # (2048 - 2048) mod 8192


def test_fakesource_close():
    src = FakeSource([0x0800])
    src.close()
    assert src.closed is True


def test_amg11master_set_offset_applies_in_sim():
    cfg = EncoderConfig(control_word=0xFFFF)   # dummy devolve 0x0000 -> raw 0
    m = Amg11Master("config/amg11.conf", cfg, sim=True)
    try:
        m.set_offset(100)
        assert m.encoder_cfg.offset == 100
        r = m.read_once(timeout=5.0)
        assert r.raw == (0 - 100) % 8192       # 8092
    finally:
        m.close()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `pytest tests/test_source_fake.py -v`
Expected: FAIL — `profibus_amg11.source` e `fakes` não existem; `Amg11Master` sem `set_offset`.

- [ ] **Step 3: Criar `profibus_amg11/source.py`**
```python
"""Abstração da fonte de leituras (DIP): o poller depende disto, não do master."""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from profibus_amg11.encoder import EncoderReading


@runtime_checkable
class ReadingSource(Protocol):
    """Fonte de leituras do encoder. Implementada por Amg11Master (prod) e FakeSource (teste)."""

    def poll(self) -> Optional[EncoderReading]:
        """Roda um passo e retorna a leitura, ou None se nada novo neste ciclo."""
        ...

    def set_offset(self, value: int) -> None:
        """Ajusta o offset (zero por software) aplicado à decodificação."""
        ...

    def close(self) -> None:
        """Libera recursos (serial)."""
        ...
```

- [ ] **Step 4: Adicionar `set_offset` em `profibus_amg11/master.py`**

Adicione o import no topo (junto aos imports existentes):
```python
from dataclasses import replace
```
E adicione o método à classe `Amg11Master` (logo após `poll`):
```python
    def set_offset(self, value):
        """Ajusta o offset por software (zero) reusando o decode existente (DRY)."""
        self.encoder_cfg = replace(self.encoder_cfg, offset=value)
```

- [ ] **Step 5: Criar `tests/fakes.py`**
```python
"""Test doubles. FakeSource implementa ReadingSource sem hardware/pyprofibus."""

from __future__ import annotations

from dataclasses import replace

from profibus_amg11.config import EncoderConfig
from profibus_amg11.encoder import EncoderReading, decode


class FakeSource:
    """Emite leituras roteirizadas. Itens int = raw16; item None = poll() -> None."""

    def __init__(self, raw16_seq, bits: int = 13):
        self._seq = list(raw16_seq)
        self._i = 0
        self._cfg = EncoderConfig(resolution_bits=bits)
        self.closed = False

    def poll(self):
        if not self._seq:
            return None
        item = self._seq[self._i % len(self._seq)]
        self._i += 1
        if item is None:
            return None
        return decode(int(item).to_bytes(2, "big"), self._cfg)

    def set_offset(self, value: int) -> None:
        self._cfg = replace(self._cfg, offset=value)

    def close(self) -> None:
        self.closed = True
```

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `pytest tests/test_source_fake.py -v`
Expected: PASS (5 testes).

- [ ] **Step 7: Suíte completa + commit**

Run: `pytest -q` (esperado: 23 antigos + 5 novos = 28 passando)
```bash
git add profibus_amg11/source.py profibus_amg11/master.py tests/fakes.py tests/test_source_fake.py
git commit -m "feat: ReadingSource (Protocol) + Amg11Master.set_offset + FakeSource (TDD)"
```

---

## Task 2: `Snapshot` + serialização pura

**Files:**
- Create: `web/__init__.py`
- Create: `web/snapshot.py`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Produces:
  - `Snapshot` (frozen dataclass): `angle_deg: float, raw: int, bytes_hex: str, offset: int, connected: bool, rate_hz: float, diag: str, ts: float`.
  - `initial_snapshot(offset: int = 0) -> Snapshot` (estado "conectando": `connected=False, diag="conectando"`).
  - `snapshot_to_dict(s: Snapshot) -> dict` (puro; `type:"reading"`, arredonda `angle_deg`→3 e `rate_hz`→1).

- [ ] **Step 1: Escrever o teste que falha** — `tests/test_snapshot.py`:
```python
from web.snapshot import Snapshot, initial_snapshot, snapshot_to_dict


def test_initial_snapshot_is_connecting():
    s = initial_snapshot(offset=5)
    assert s.connected is False
    assert s.offset == 5
    assert s.diag == "conectando"


def test_snapshot_to_dict_shape_and_rounding():
    s = Snapshot(angle_deg=90.123456, raw=2048, bytes_hex="0800", offset=0,
                 connected=True, rate_hz=47.27, diag="OK", ts=123.0)
    d = snapshot_to_dict(s)
    assert d["type"] == "reading"
    assert d["angle_deg"] == 90.123
    assert d["rate_hz"] == 47.3
    assert d["raw"] == 2048
    assert d["bytes_hex"] == "0800"
    assert d["connected"] is True
    assert set(d.keys()) == {
        "type", "angle_deg", "raw", "bytes_hex", "offset",
        "connected", "rate_hz", "diag", "ts",
    }
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `pytest tests/test_snapshot.py -v`
Expected: FAIL — `web.snapshot` não existe.

- [ ] **Step 3: Criar `web/__init__.py`** (vazio):
```python
```

- [ ] **Step 4: Criar `web/snapshot.py`**
```python
"""Estado publicado pelo poller + serialização pura (testável isolada)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    angle_deg: float
    raw: int
    bytes_hex: str
    offset: int
    connected: bool
    rate_hz: float
    diag: str
    ts: float


def initial_snapshot(offset: int = 0) -> Snapshot:
    return Snapshot(angle_deg=0.0, raw=0, bytes_hex="", offset=offset,
                    connected=False, rate_hz=0.0, diag="conectando", ts=0.0)


def snapshot_to_dict(s: Snapshot) -> dict:
    return {
        "type": "reading",
        "angle_deg": round(s.angle_deg, 3),
        "raw": s.raw,
        "bytes_hex": s.bytes_hex,
        "offset": s.offset,
        "connected": s.connected,
        "rate_hz": round(s.rate_hz, 1),
        "diag": s.diag,
        "ts": s.ts,
    }
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `pytest tests/test_snapshot.py -v`
Expected: PASS (2 testes).

- [ ] **Step 6: Commit**
```bash
git add web/__init__.py web/snapshot.py tests/test_snapshot.py
git commit -m "feat: Snapshot + snapshot_to_dict (serializacao pura, TDD)"
```

---

## Task 3: `EncoderPoller` (thread + snapshot + zero)

**Files:**
- Create: `web/poller.py`
- Test: `tests/test_poller.py`

**Interfaces:**
- Consumes: `ReadingSource`, `Snapshot`, `initial_snapshot` (Tasks 1-2).
- Produces:
  - `EncoderPoller(source: ReadingSource, period: int, initial_offset: int = 0, now=time.monotonic, stale_after: float = 0.5, tick_sleep: float = 0.005)`.
  - `step() -> Snapshot` (uma iteração determinística: drena comandos, lê uma leitura, atualiza snapshot).
  - `zero() -> None`, `clear_zero() -> None`, `snapshot() -> Snapshot` (thread-safe).
  - `start() -> None`, `stop() -> None` (ciclo de vida da thread; `stop` chama `source.close()`).

- [ ] **Step 1: Escrever o teste que falha** — `tests/test_poller.py`:
```python
from web.poller import EncoderPoller
from fakes import FakeSource


class FakeClock:
    """Relógio injetável: retorna tempos sucessivos (sem tempo real)."""
    def __init__(self, times):
        self._times = list(times)
        self._i = 0

    def __call__(self):
        t = self._times[min(self._i, len(self._times) - 1)]
        self._i += 1
        return t


def test_step_updates_snapshot():
    p = EncoderPoller(FakeSource([0x0800]), period=8192, now=FakeClock([1.0, 2.0]))
    snap = p.step()
    assert snap.connected is True
    assert snap.raw == 0x0800
    assert abs(snap.angle_deg - 90.0) < 1e-6


def test_zero_command_zeroes_next_reading():
    p = EncoderPoller(FakeSource([0x0800]), period=8192, now=FakeClock([1.0, 2.0, 3.0]))
    p.step()                  # raw 2048
    p.zero()                  # enfileira
    snap = p.step()           # drena zero -> offset 2048 -> proxima leitura raw 0
    assert snap.raw == 0
    assert snap.offset == 0x0800


def test_clear_zero_resets_offset():
    p = EncoderPoller(FakeSource([0x0800]), period=8192, now=FakeClock([1, 2, 3, 4]))
    p.step(); p.zero(); p.step()
    p.clear_zero()
    snap = p.step()
    assert snap.offset == 0
    assert snap.raw == 0x0800


def test_rate_hz_uses_injected_clock():
    # leituras a cada 0.05s -> ~20 Hz
    p = EncoderPoller(FakeSource([0x0800, 0x0800]), period=8192,
                      now=FakeClock([1.00, 1.05, 1.10]))
    p.step()                  # primeira leitura: sem rate ainda
    snap = p.step()           # dt = 0.05 -> 20 Hz
    assert abs(snap.rate_hz - 20.0) < 1e-6


def test_no_reading_marks_stale():
    p = EncoderPoller(FakeSource([0x0800, None]), period=8192,
                      now=FakeClock([1.0, 5.0]), stale_after=0.5)
    p.step()                  # leitura ok
    snap = p.step()           # None, clock pulou 4s > stale_after
    assert snap.connected is False
    assert snap.diag == "sem leitura"


def test_stop_closes_source_without_start():
    src = FakeSource([0x0800])
    p = EncoderPoller(src, period=8192)
    p.stop()                  # sem start(): thread é None, só fecha a fonte
    assert src.closed is True
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `pytest tests/test_poller.py -v`
Expected: FAIL — `web.poller` não existe.

- [ ] **Step 3: Criar `web/poller.py`**
```python
"""Serviço de aplicação: thread dona do ReadingSource, mantém um Snapshot vivo."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

from web.snapshot import Snapshot, initial_snapshot


class EncoderPoller:
    def __init__(self, source, period, initial_offset=0,
                 now=time.monotonic, stale_after=0.5, tick_sleep=0.005):
        self._source = source
        self._period = period
        self._offset = initial_offset
        self._now = now
        self._stale_after = stale_after
        self._tick_sleep = tick_sleep

        self._lock = threading.Lock()
        self._snap = initial_snapshot(offset=initial_offset)
        self._last_raw = 0
        self._last_rx = None      # tempo da última leitura válida
        self._rate = 0.0
        self._pending = []        # fila de comandos
        self._thread = None
        self._running = False

    # --- API de comandos (chamada pela thread web) ---
    def zero(self):
        with self._lock:
            self._pending.append("zero")

    def clear_zero(self):
        with self._lock:
            self._pending.append("clear_zero")

    def snapshot(self):
        with self._lock:
            return self._snap

    # --- núcleo determinístico (testável sem thread) ---
    def step(self):
        with self._lock:
            cmds, self._pending = self._pending, []
        for c in cmds:
            if c == "zero":
                self._offset = (self._last_raw + self._offset) % self._period
                self._source.set_offset(self._offset)
            elif c == "clear_zero":
                self._offset = 0
                self._source.set_offset(0)

        reading = self._source.poll()
        now = self._now()

        if reading is not None:
            if self._last_rx is not None:
                dt = now - self._last_rx
                if dt > 0:
                    inst = 1.0 / dt
                    self._rate = inst if self._rate == 0.0 else 0.8 * self._rate + 0.2 * inst
            self._last_rx = now
            self._last_raw = reading.raw
            snap = Snapshot(angle_deg=reading.angle_deg, raw=reading.raw,
                            bytes_hex=reading.bytes_hex, offset=self._offset,
                            connected=True, rate_hz=self._rate, diag="OK", ts=now)
        else:
            connected = self._last_rx is not None and (now - self._last_rx) < self._stale_after
            with self._lock:
                prev = self._snap
            snap = replace(prev, offset=self._offset, connected=connected,
                           rate_hz=self._rate if connected else 0.0,
                           diag="OK" if connected else "sem leitura", ts=now)

        with self._lock:
            self._snap = snap
        return snap

    # --- ciclo de vida da thread ---
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            try:
                self.step()
            except Exception as e:  # nunca derruba a thread; reporta no snapshot
                with self._lock:
                    self._snap = replace(self._snap, connected=False,
                                         diag="erro: %s" % e, ts=self._now())
                time.sleep(0.2)
            if self._tick_sleep:
                time.sleep(self._tick_sleep)

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._source.close()
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `pytest tests/test_poller.py -v`
Expected: PASS (6 testes).

- [ ] **Step 5: Commit**
```bash
git add web/poller.py tests/test_poller.py
git commit -m "feat: EncoderPoller (step deterministico, zero, taxa c/ relogio injetado) TDD"
```

---

## Task 4: Servidor Flask + flask-sock + `serve.py`

**Files:**
- Create: `web/server.py`
- Create: `web/static/index.html` (mínimo; substituído na Task 5)
- Create: `serve.py`
- Modify: `requirements.txt` (adicionar `flask`, `flask-sock`)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `EncoderPoller`, `snapshot_to_dict`, `FakeSource` (testes).
- Produces:
  - `create_app(poller) -> flask.Flask` (rota `GET /` → `index.html`; estáticos em `/...`; WS em `/ws`).
  - `serve.py` (`python serve.py [--host --port --sim --conf --encoder]`).

- [ ] **Step 1: Instalar deps e atualizar `requirements.txt`**

Adicione ao `requirements.txt`:
```
flask>=3.0
flask-sock>=0.7
```
Run: `. .venv/bin/activate && pip install -q 'flask>=3.0' 'flask-sock>=0.7' && python -c "import flask, flask_sock; print('ok')"`
Expected: imprime `ok`.

- [ ] **Step 2: Escrever o teste que falha** — `tests/test_server.py`:
```python
from web.server import create_app
from web.poller import EncoderPoller
from fakes import FakeSource


def make_app():
    poller = EncoderPoller(FakeSource([0x0800]), period=8192)
    poller.step()  # popula um snapshot
    return create_app(poller)


def test_index_served():
    app = make_app()
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'id="app"' in resp.data


def test_static_styles_route_is_clean():
    # styles.css só chega na Task 5; aqui garantimos que a app não quebra na rota.
    app = make_app()
    client = app.test_client()
    resp = client.get("/styles.css")
    assert resp.status_code in (200, 404)
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `pytest tests/test_server.py -v`
Expected: FAIL — `web.server` não existe.

- [ ] **Step 4: Criar `web/static/index.html` (mínimo)**
```html
<!doctype html>
<html lang="pt-br">
<head><meta charset="utf-8"><title>PROFIBUS · AMG11</title></head>
<body><div id="app">carregando…</div></body>
</html>
```

- [ ] **Step 5: Criar `web/server.py`**
```python
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
            ws.send(json.dumps(snapshot_to_dict(poller.snapshot())))
            try:
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
```

- [ ] **Step 6: Criar `serve.py`**
```python
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
```

- [ ] **Step 7: Rodar e confirmar que passa**

Run: `pytest tests/test_server.py -v`
Expected: PASS (2 testes).

- [ ] **Step 8: Smoke manual no sim**

Run: `. .venv/bin/activate && (python serve.py --sim --port 8601 &) && sleep 2 && curl -s localhost:8601/ | grep -q 'id="app"' && echo SMOKE_OK && pkill -f 'serve.py --sim'`
Expected: imprime `SMOKE_OK`.

- [ ] **Step 9: Suíte completa + commit**

Run: `pytest -q` (28 + 2 = 30 passando)
```bash
git add web/server.py web/static/index.html serve.py requirements.txt tests/test_server.py
git commit -m "feat: servidor Flask + flask-sock (/ws) + serve.py (TDD)"
```

---

## Task 5: Frontend Preact (vendorizado, painel de instrumento)

**Files:**
- Create: `web/static/vendor/preact.module.js`, `hooks.module.js`, `htm.module.js` (baixados)
- Create: `web/static/vendor/*.woff2` (fontes; ver passo) + fallback de sistema
- Modify: `web/static/index.html` (versão final com importmap)
- Create: `web/static/app.js` (dashboard Preact)
- Create: `web/static/styles.css` (tokens + componentes)
- Test: `tests/test_frontend_assets.py`

**Interfaces:**
- Consome o contrato do WS da Task 4: mensagens `{type:"reading", angle_deg, raw, bytes_hex, offset, connected, rate_hz, diag, ts}`; envia `{cmd:"zero"}` / `{cmd:"clear_zero"}`.

- [ ] **Step 1: Vendorizar Preact + htm** (sandbox tem internet)
```bash
cd ~/repos/pi5-profibus-amg11 && mkdir -p web/static/vendor
curl -sL https://unpkg.com/preact@10.24.3/dist/preact.module.js       -o web/static/vendor/preact.module.js
curl -sL https://unpkg.com/preact@10.24.3/hooks/dist/hooks.module.js   -o web/static/vendor/hooks.module.js
curl -sL https://unpkg.com/htm@3.1.1/dist/htm.module.js                -o web/static/vendor/htm.module.js
for f in preact hooks htm; do test -s web/static/vendor/$f.module.js || echo "FALHOU: $f"; done
wc -c web/static/vendor/*.module.js
```
Expected: três arquivos > 1KB, sem "FALHOU". (Se um URL 404, pegue o `.module.js` equivalente da versão atual da lib no unpkg — o requisito é um ESM autocontido.)

- [ ] **Step 2: Vendorizar fontes** (grotesca + mono; OFL). Numerais em mono são o destaque.
```bash
curl -sL "https://cdn.jsdelivr.net/fontsource/fonts/space-grotesk@5.1.0/latin-500-normal.woff2"  -o web/static/vendor/space-grotesk-500.woff2
curl -sL "https://cdn.jsdelivr.net/fontsource/fonts/space-grotesk@5.1.0/latin-700-normal.woff2"  -o web/static/vendor/space-grotesk-700.woff2
curl -sL "https://cdn.jsdelivr.net/fontsource/fonts/jetbrains-mono@5.1.0/latin-500-normal.woff2" -o web/static/vendor/jetbrains-mono-500.woff2
for f in space-grotesk-500 space-grotesk-700 jetbrains-mono-500; do test -s web/static/vendor/$f.woff2 || echo "SEM_FONTE: $f"; done
```
Expected: três `.woff2` > 5KB. **Se alguma falhar** (`SEM_FONTE`), siga sem ela: o `styles.css` já tem fallback de sistema (`ui-sans-serif`/`ui-monospace`) — não use Inter.

- [ ] **Step 3: Escrever o teste que falha** — `tests/test_frontend_assets.py`:
```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"


def test_vendor_modules_present_and_nonempty():
    for name in ("preact.module.js", "hooks.module.js", "htm.module.js"):
        f = STATIC / "vendor" / name
        assert f.exists() and f.stat().st_size > 1024, name


def test_index_uses_importmap_and_app_module():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'type="importmap"' in html
    assert '/vendor/preact.module.js' in html
    assert 'app.js' in html
    assert 'id="app"' in html


def test_app_js_uses_ws_and_zero_command():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "/ws" in js
    assert '"zero"' in js or "'zero'" in js


def test_styles_no_inter_default():
    css = (STATIC / "styles.css").read_text(encoding="utf-8").lower()
    assert "inter" not in css   # fonte banida como default
```

- [ ] **Step 4: Rodar e confirmar que falha**

Run: `pytest tests/test_frontend_assets.py -v`
Expected: FAIL — `app.js`/`styles.css` não existem e o `index.html` ainda é o mínimo.

- [ ] **Step 5: Escrever `web/static/index.html` (final, com importmap)**
```html
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PROFIBUS · AMG11</title>
  <link rel="stylesheet" href="/styles.css">
  <script type="importmap">
  {
    "imports": {
      "preact": "/vendor/preact.module.js",
      "preact/hooks": "/vendor/hooks.module.js",
      "htm": "/vendor/htm.module.js"
    }
  }
  </script>
</head>
<body>
  <div id="app">carregando…</div>
  <script type="module" src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 6: Escrever `web/static/styles.css`** (tokens + painel de instrumento dark)
```css
@font-face{font-family:"Space Grotesk";src:url("/vendor/space-grotesk-500.woff2") format("woff2");font-weight:500;font-display:swap}
@font-face{font-family:"Space Grotesk";src:url("/vendor/space-grotesk-700.woff2") format("woff2");font-weight:700;font-display:swap}
@font-face{font-family:"JetBrains Mono";src:url("/vendor/jetbrains-mono-500.woff2") format("woff2");font-weight:500;font-display:swap}

:root{
  --bg:#0c0e12; --panel:#13161c; --panel-2:#171b22; --hair:rgba(255,255,255,.06);
  --ink:#e7ebf0; --ink-dim:#8b94a3; --accent:#34d399; --bad:#f87171;
  --sans:"Space Grotesk",ui-sans-serif,system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --r:18px; --ease:cubic-bezier(.32,.72,0,1);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:24px}
#app{width:100%;max-width:520px}

.panel{background:var(--panel);border:1px solid var(--hair);border-radius:var(--r);
  padding:22px;box-shadow:0 18px 50px -20px rgba(0,0,0,.7)}
.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
.title{font-weight:700;letter-spacing:.04em;font-size:14px}
.badge{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);
  font-size:12px;color:var(--ink-dim)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--bad)}
.dot.on{background:var(--accent);box-shadow:0 0 0 0 rgba(52,211,153,.6);animation:pulse 1.8s var(--ease) infinite}
@keyframes pulse{70%{box-shadow:0 0 0 7px rgba(52,211,153,0)}100%{box-shadow:0 0 0 0 rgba(52,211,153,0)}}
@media (prefers-reduced-motion:reduce){.dot.on{animation:none}}

.gauge{position:relative;width:260px;height:260px;margin:6px auto 14px}
.gauge .ring{position:absolute;inset:0;border-radius:50%;
  background:var(--panel-2);border:1px solid var(--hair);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.05), inset 0 0 40px rgba(0,0,0,.5)}
.gauge .needle{position:absolute;left:50%;top:50%;width:3px;height:42%;
  background:linear-gradient(var(--accent),transparent);transform-origin:bottom center;
  transform:translate(-50%,-100%) rotate(0deg);transition:transform .12s var(--ease)}
.gauge .hub{position:absolute;left:50%;top:50%;width:14px;height:14px;border-radius:50%;
  background:var(--accent);transform:translate(-50%,-50%)}
.gauge .val{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  flex-direction:column}
.gauge .deg{font-family:var(--mono);font-size:40px;font-weight:500}
.gauge .deg.stale{color:var(--ink-dim)}

.rows{display:grid;grid-template-columns:1fr 1fr;gap:10px 18px;font-family:var(--mono);
  font-size:13px;color:var(--ink-dim);margin:4px 4px 18px}
.rows b{color:var(--ink);font-weight:500}

.actions{display:flex;gap:10px}
button{flex:1;font-family:var(--sans);font-weight:500;font-size:14px;color:#06231a;
  background:var(--accent);border:0;border-radius:999px;padding:12px 16px;cursor:pointer;
  transition:transform .12s var(--ease),filter .12s var(--ease)}
button.ghost{background:transparent;color:var(--ink);border:1px solid var(--hair)}
button:active{transform:translateY(1px) scale(.99)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
```

- [ ] **Step 7: Escrever `web/static/app.js`** (Preact + htm)
```javascript
import { h, render } from "preact";
import { useState, useEffect, useRef } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

function useSocket() {
  const [snap, setSnap] = useState({ connected: false, diag: "conectando", angle_deg: 0,
    raw: 0, bytes_hex: "", offset: 0, rate_hz: 0 });
  const ws = useRef(null);
  useEffect(() => {
    let stop = false;
    function connect() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const s = new WebSocket(`${proto}://${location.host}/ws`);
      ws.current = s;
      s.onmessage = (e) => setSnap(JSON.parse(e.data));
      s.onclose = () => { if (!stop) setTimeout(connect, 800); };
    }
    connect();
    return () => { stop = true; ws.current && ws.current.close(); };
  }, []);
  const send = (cmd) => ws.current && ws.current.readyState === 1 && ws.current.send(JSON.stringify({ cmd }));
  return { snap, send };
}

function App() {
  const { snap, send } = useSocket();
  const live = snap.connected;
  const angle = Number(snap.angle_deg || 0);
  return html`
    <div class="panel">
      <div class="top">
        <div class="title">PROFIBUS · AMG11</div>
        <div class="badge"><span class=${"dot" + (live ? " on" : "")}></span>
          ${live ? `${(snap.rate_hz || 0).toFixed(0)} Hz` : (snap.diag || "sem leitura")}</div>
      </div>

      <div class="gauge">
        <div class="ring"></div>
        <div class="needle" style=${`transform:translate(-50%,-100%) rotate(${angle}deg)`}></div>
        <div class="hub"></div>
        <div class="val"><div class=${"deg" + (live ? "" : " stale")}>${angle.toFixed(1)}°</div></div>
      </div>

      <div class="rows">
        <div>bruto <b>${snap.raw} / 8191</b></div>
        <div>bytes <b>${snap.bytes_hex || "--"}</b></div>
        <div>offset <b>${snap.offset}</b></div>
        <div>diag <b>${snap.diag}</b></div>
      </div>

      <div class="actions">
        <button onClick=${() => send("zero")}>Zerar aqui</button>
        <button class="ghost" onClick=${() => send("clear_zero")}>Desfazer</button>
      </div>
    </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
```

- [ ] **Step 8: Rodar e confirmar que passa**

Run: `pytest tests/test_frontend_assets.py -v`
Expected: PASS (4 testes).

- [ ] **Step 9: Smoke manual no sim** (servir e abrir no browser)
```bash
. .venv/bin/activate && python serve.py --sim --port 8602
```
Abra `http://localhost:8602` (ou `http://<ip-do-pi>:8602`). Esperado: mostrador com a agulha girando, badge "conectado", numerais em mono; clicar "Zerar aqui" leva o ângulo a ~0. `Ctrl-C` encerra.

- [ ] **Step 10: Suíte completa + commit**

Run: `pytest -q` (30 + 4 = 34 passando)
```bash
git add web/static
git commit -m "feat: dashboard Preact vendorizado (painel de instrumento, zerar) TDD"
```

---

## Task 6: Revisão final com a skill `code-review`

Depois de Tasks 1–5 e com `pytest -q` verde, rode a skill de code review sobre todo o diff do v1 e endereça os achados antes de fechar. (No fluxo subagent-driven, esta task substitui/complementa o "final reviewer": use explicitamente a skill `code-review`.)

- [ ] **Step 1: Garantir suíte verde e branch limpo**

Run: `pytest -q` (34 passando) e `git status` (sem pendências não commitadas).

- [ ] **Step 2: Rodar a skill `code-review` no diff da v1**

Invoque a skill **`code-review`** com esforço alto (ex.: `/code-review high`), cobrindo o diff de toda a v1: `profibus_amg11/source.py`, `profibus_amg11/master.py` (`set_offset`), `web/snapshot.py`, `web/poller.py`, `web/server.py`, `serve.py`, `web/static/**`, `tests/**`.
Foco específico:
- **Corretude:** thread-safety do `EncoderPoller` (mutação de offset só na thread do poller; acesso ao snapshot sob lock), math do zero (`(last_raw + offset) % period`), contrato do WS (chaves/serialização), e o loop do `/ws` (encerrar limpo na desconexão).
- **Reuso/simplificação:** sem duplicar o `decode`; `Snapshot`/serialização coesos; `serve.py` enxuto.
- **Aderência ao spec/skills:** sem Inter default, um acento, `prefers-reduced-motion`, sem emoji, contraste AA.

- [ ] **Step 3: Endereçar os achados**

Para cada achado relevante: escrever/ajustar o teste que o captura, corrigir, `pytest -q`, e commitar. Reexecutar a `code-review` se houver mudança significativa. Achados de menor relevância podem ser anotados e adiados conscientemente (registre o motivo).

- [ ] **Step 4: Commit final**
```bash
git add -A
git commit -m "chore: ajustes da revisao final (code-review) do dashboard v1"
```

---

## Verificações finais

- [ ] `pytest -q` → tudo verde (lib/source + snapshot + poller + server + frontend assets).
- [ ] `python serve.py --sim` → dashboard abre, agulha se move, "Zerar aqui" zera.
- [ ] No Pi3 real: `python serve.py` (sem `--sim`) → leitura ao vivo do encoder no browser via LAN.
- [ ] **Skill `code-review` executada (Task 6)** e achados endereçados.
- [ ] Cobertura do spec: ReadingSource/DIP ✓ (T1), set_offset ✓ (T1), Snapshot+serialização ✓ (T2), poller/thread/zero/rate ✓ (T3), Flask+flask-sock/WS/serve ✓ (T4), Preact vendorizado/instrumento/estados/AA/sem-Inter ✓ (T5), revisão final via skill code-review ✓ (T6), zero só-sessão ✓ (T3), TDD sem test-smells (FakeSource, relógio injetado, step síncrono) ✓.
