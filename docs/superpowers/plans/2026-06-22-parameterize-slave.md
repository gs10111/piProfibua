# Parametrizar Escravo + I/O cru (B2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Parametrizar ao vivo qualquer escravo (GSD em memória + módulos + endereço + tamanhos manuais) até o Data_Exchange e ler/escrever I/O cru, via um novo modo `generic` do `BusController`.

**Architecture:** Domínio `profibus_amg11/generic.py` (monta `DpSlaveDesc` + roda DPM) atrás de `GenericSource`; app `web/generic_poller.py` (`GenericPoller` → `IoSnapshot`); `BusController` ganha o modo `generic` (dono único da serial). Frontend: aba GSD com "Parametrizar e ler" + painel I/O.

**Tech Stack:** Python 3.12, pyprofibus (DpSlaveDesc/DPM1), Flask+flask-sock, Preact, pytest.

## Global Constraints

- **Sem libs novas.** Tamanhos de I/O **manuais** (auto-derivação deferida). Sem decode (raw).
- **Dono único da serial:** `generic`/`scanning`/`exchange` nunca compartilham a porta.
- **Determinismo testável:** lógica em `step()`; relógio/factories injetados; fakes, sem hardware, sem `sleep` em teste.
- **`create_app`/factories opcionais:** A/B1/v1 seguem verdes.
- **Honestidade:** chegar ao DX depende de ident/cfg/prm/tamanho baterem; se não, mostra o diag, não trava.
- **Frontend v1/A/B1:** sem emoji, sem Inter, AA, mono no hex, copy direta.
- Commits PT, terminando com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: GenericDpMaster + make_generic_slave_desc (domínio)

**Files:** Create `profibus_amg11/generic.py`; Test `tests/test_generic.py`.

**Interfaces:**
- Produces: `GenericError`; `make_generic_slave_desc(gsd_bytes, address, modules, input_size, output_size) -> DpSlaveDesc`; `GenericDpMaster(conf_path, gsd_bytes, address, modules, input_size, output_size, baud=None, master_addr=None, sim=False, debug=False)` com `poll()->bytes|None`, `set_output(bytes)`, `connected` (prop), `diag` (prop), `close()`.

- [ ] **Step 1: Failing tests** (com as 2 GSDs reais; sem barramento)

```python
# tests/test_generic.py
from pathlib import Path
import pytest
from profibus_amg11.generic import make_generic_slave_desc, GenericError, GenericDpMaster

GSD = Path(__file__).resolve().parent.parent / "gsd"
AMG11 = (GSD / "PB13DPV0.gsd").read_bytes()
IFM = (GSD / "IFM_0E75.gsd").read_bytes()
CONF = str(Path(__file__).resolve().parent.parent / "config" / "amg11.conf")


def test_slave_desc_from_amg11():
    d = make_generic_slave_desc(AMG11, 3, ["16 Bit Class 2 Encoder "], 2, 2)
    assert d.identNumber == 0x059B
    assert d.slaveAddr == 3
    assert d.inputSize == 2 and d.outputSize == 2


def test_slave_desc_from_ifm():
    s = make_generic_slave_desc(IFM, 9, ["Class 2 Multiturn"], 4, 0)
    assert s.identNumber == 0x0E75 and s.slaveAddr == 9


def test_unknown_module_raises():
    with pytest.raises(GenericError):
        make_generic_slave_desc(AMG11, 3, ["nao existe"], 2, 2)


def test_generic_master_constructs_in_sim():
    m = GenericDpMaster(CONF, AMG11, 3, ["16 Bit Class 2 Encoder "], 2, 2, sim=True)
    try:
        assert isinstance(m.connected, bool)
        m.set_output(b"\x00\x00")
        m.poll()  # não deve lançar
    finally:
        m.close()
```

- [ ] **Step 2: Run → fail.** `.venv/bin/python -m pytest tests/test_generic.py -q`

- [ ] **Step 3: Implement `profibus_amg11/generic.py`**

```python
"""Mestre DP genérico: parametriza um escravo de um GSD em memória e troca I/O cru."""
from __future__ import annotations

import contextlib
from pathlib import Path

from pyprofibus import PbConf
from pyprofibus.gsd.interp import GsdInterp
from pyprofibus.gsd.parser import GsdError

from profibus_amg11.master import _chdir


class GenericError(Exception):
    pass


class _GenericSlaveConf:
    """slaveConf leve com os atributos que o DpSlaveDesc lê."""

    def __init__(self, gsd, addr, input_size, output_size):
        self.gsd = gsd
        self.addr = addr
        self.name = "generic-%d" % addr
        self.index = 1
        self.inputSize = input_size
        self.outputSize = output_size
        self.diagPeriod = 0
        self.syncMode = False
        self.freezeMode = False
        self.groupMask = 1
        self.watchdogMs = 1000


def make_generic_slave_desc(gsd_bytes, address, modules, input_size, output_size):
    from pyprofibus.dp_master import DpSlaveDesc
    try:
        gsd = GsdInterp.fromBytes(bytes(gsd_bytes), filename="<generic>")
        chosen = list(modules or [])
        if chosen:
            gsd.clearConfiguredModules()
            for name in chosen:
                gsd.setConfiguredModule(name)
        conf = _GenericSlaveConf(gsd, address, input_size, output_size)
        desc = DpSlaveDesc(conf)
        desc.setCfgDataElements(gsd.getCfgDataElements())
        desc.setUserPrmData(gsd.getUserPrmData())
        desc.setSyncMode(conf.syncMode)
        desc.setFreezeMode(conf.freezeMode)
        desc.setGroupMask(conf.groupMask)
        desc.setWatchdog(conf.watchdogMs)
        return desc
    except GsdError as e:
        raise GenericError(str(e))


class GenericDpMaster:
    """DPM1 de um escravo genérico; troca DX e expõe I/O cru. (GenericSource)"""

    def __init__(self, conf_path, gsd_bytes, address, modules,
                 input_size, output_size, baud=None, master_addr=None,
                 sim=False, debug=False):
        self._out = bytearray(output_size)
        conf_path = Path(conf_path).resolve()
        project_root = conf_path.parent.parent
        with _chdir(project_root):
            conf = PbConf.fromFile(str(conf_path))
            if sim:
                conf.phyType = "dummyslave"
            if baud is not None:
                conf.phyBaud = baud
            if master_addr is not None:
                conf.dpMasterAddr = master_addr
            conf.debug = 2 if debug else 0
            phy = conf.makePhy()             # sim: echoDXSize vem do .conf (slaveConfs intactos)
            self.master = conf.makeDPM(phy=phy)   # mestre sem escravos
        try:
            self.slave = make_generic_slave_desc(gsd_bytes, address, modules,
                                                 input_size, output_size)
            self.master.addSlave(self.slave)
            self.master.initialize()
        except Exception:
            self.close()
            raise

    def poll(self):
        self.slave.setMasterOutData(bytearray(self._out))
        handled = self.master.run()
        if handled is self.slave:
            data = self.slave.getMasterInData()
            if data is not None:
                return bytes(data)
        return None

    def set_output(self, data):
        self._out = bytearray(data)

    @property
    def connected(self):
        try:
            return bool(self.slave.isConnected())
        except Exception:
            return False

    @property
    def diag(self):
        return "OK" if self.connected else "conectando"

    def close(self):
        with contextlib.suppress(Exception):
            self.master.destroy()
```

- [ ] **Step 4: Run → pass.** (test_generic_master_constructs_in_sim pode levar ~1s no dummy.)
- [ ] **Step 5: Commit** — `git add profibus_amg11/generic.py tests/test_generic.py && git commit -m "feat: GenericDpMaster + make_generic_slave_desc (parametriza GSD em memória)"`

---

### Task 2: IoSnapshot + serialização

**Files:** Modify `web/snapshot.py`; Test `tests/test_snapshot.py`.

**Interfaces:** Produces `IoSnapshot(active, address, connected, diag, in_hex, out_hex, input_size, output_size, rate_hz, ts)`; `idle_io_snapshot(address=0, input_size=0, output_size=0)`; `io_snapshot_to_dict(s)`.

- [ ] **Step 1: Failing test**

```python
# tests/test_snapshot.py (acrescentar imports + teste)
from web.snapshot import IoSnapshot, idle_io_snapshot, io_snapshot_to_dict


def test_io_snapshot_to_dict_shape():
    s = IoSnapshot(active=True, address=9, connected=True, diag="OK",
                   in_hex="1234", out_hex="00", input_size=2, output_size=1,
                   rate_hz=12.34, ts=1.0)
    d = io_snapshot_to_dict(s)
    assert d["type"] == "io" and d["active"] is True and d["address"] == 9
    assert d["in_hex"] == "1234" and d["rate_hz"] == 12.3
    assert idle_io_snapshot(address=9).active is False
```

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement (acrescentar a `web/snapshot.py`)**

```python
@dataclass(frozen=True)
class IoSnapshot:
    active: bool
    address: int
    connected: bool
    diag: str
    in_hex: str
    out_hex: str
    input_size: int
    output_size: int
    rate_hz: float
    ts: float


def idle_io_snapshot(address: int = 0, input_size: int = 0,
                     output_size: int = 0) -> IoSnapshot:
    return IoSnapshot(active=False, address=address, connected=False, diag="",
                      in_hex="", out_hex="", input_size=input_size,
                      output_size=output_size, rate_hz=0.0, ts=0.0)


def io_snapshot_to_dict(s: IoSnapshot) -> dict:
    return {
        "type": "io", "active": s.active, "address": s.address,
        "connected": s.connected, "diag": s.diag, "in_hex": s.in_hex,
        "out_hex": s.out_hex, "input_size": s.input_size,
        "output_size": s.output_size, "rate_hz": round(s.rate_hz, 1), "ts": s.ts,
    }
```

- [ ] **Step 4: Run → pass.** **Step 5: Commit** — `git add web/snapshot.py tests/test_snapshot.py && git commit -m "feat: IoSnapshot + io_snapshot_to_dict"`

---

### Task 3: GenericSource + ParamSpec + GenericPoller

**Files:** Create `web/generic_poller.py`; Test `tests/test_generic_poller.py`.

**Interfaces:** Produces `ParamSpec(gsd, address, modules, input_size, output_size)` (frozen); `GenericSource` (Protocol: `poll()->bytes|None`, `set_output(bytes)`, `connected` prop, `diag` prop, `close()`); `GenericPoller(source, address, input_size, output_size, now=time.monotonic, stale_after=0.5)` com `step()->IoSnapshot`, `snapshot()`, `set_output(bytes)`, `stop()`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_generic_poller.py
from web.generic_poller import GenericPoller
from web.snapshot import IoSnapshot


class FakeClock:
    def __init__(self, t): self._t=list(t); self._i=0
    def __call__(self): v=self._t[min(self._i,len(self._t)-1)]; self._i+=1; return v


class FakeGenericSource:
    def __init__(self, seq, connected=True):
        self._seq=list(seq); self._i=0; self._connected=connected
        self.out=None; self.closed=False
    def poll(self):
        v=self._seq[min(self._i,len(self._seq)-1)]; self._i+=1; return v
    def set_output(self, data): self.out=bytes(data)
    @property
    def connected(self): return self._connected
    @property
    def diag(self): return "OK" if self._connected else "conectando"
    def close(self): self.closed=True


def test_step_reads_input():
    p = GenericPoller(FakeGenericSource([b"\x12\x34"]), 9, 2, 0,
                      now=FakeClock([1.0, 2.0]))
    s = p.step()
    assert s.active and s.connected and s.in_hex == "1234" and s.address == 9


def test_rate_from_clock():
    p = GenericPoller(FakeGenericSource([b"\x00", b"\x00"]), 9, 1, 0,
                      now=FakeClock([1.00, 1.05, 1.10]))
    p.step(); s = p.step()
    assert abs(s.rate_hz - 20.0) < 1e-6


def test_set_output_forwarded():
    src = FakeGenericSource([None])
    p = GenericPoller(src, 9, 0, 1)
    p.set_output(b"\xff")
    assert src.out == b"\xff" and p.snapshot().out_hex == "ff"


def test_stale_when_no_reading():
    p = GenericPoller(FakeGenericSource([b"\x00", None], connected=True), 9, 1, 0,
                      now=FakeClock([1.0, 5.0]), stale_after=0.5)
    p.step(); s = p.step()
    assert s.diag == "sem leitura"


def test_stop_closes_source():
    src = FakeGenericSource([None]); GenericPoller(src, 9, 0, 0).stop()
    assert src.closed is True
```

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement `web/generic_poller.py`**

```python
"""Motor do modo generic: mantém um IoSnapshot vivo lendo um GenericSource."""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple, runtime_checkable

from web.snapshot import IoSnapshot, idle_io_snapshot


@dataclass(frozen=True)
class ParamSpec:
    gsd: str
    address: int
    modules: Tuple[str, ...]
    input_size: int
    output_size: int


@runtime_checkable
class GenericSource(Protocol):
    def poll(self) -> Optional[bytes]: ...
    def set_output(self, data) -> None: ...
    @property
    def connected(self) -> bool: ...
    @property
    def diag(self) -> str: ...
    def close(self) -> None: ...


class GenericPoller:
    def __init__(self, source, address, input_size, output_size,
                 now=time.monotonic, stale_after=0.5):
        self._source = source
        self._address = address
        self._input_size = input_size
        self._output_size = output_size
        self._now = now
        self._stale_after = stale_after
        self._last_rx = None
        self._rate = 0.0
        self._snap = idle_io_snapshot(address=address, input_size=input_size,
                                      output_size=output_size)

    def step(self) -> IoSnapshot:
        data = self._source.poll()
        now = self._now()
        connected = self._source.connected
        if data is not None:
            if self._last_rx is not None:
                dt = now - self._last_rx
                if dt > 0:
                    inst = 1.0 / dt
                    self._rate = inst if self._rate == 0.0 else 0.8 * self._rate + 0.2 * inst
            self._last_rx = now
            in_hex, diag, rate = bytes(data).hex(), "OK", self._rate
        else:
            in_hex = self._snap.in_hex
            if self._last_rx is None:
                diag, rate = (self._source.diag or "conectando"), 0.0
            elif (now - self._last_rx) >= self._stale_after:
                diag, rate = "sem leitura", 0.0
            else:
                diag, rate = "OK", self._rate
        self._snap = IoSnapshot(active=True, address=self._address,
                                connected=connected, diag=diag, in_hex=in_hex,
                                out_hex=self._snap.out_hex,
                                input_size=self._input_size,
                                output_size=self._output_size,
                                rate_hz=rate, ts=now)
        return self._snap

    def snapshot(self) -> IoSnapshot:
        return self._snap

    def set_output(self, data):
        self._source.set_output(data)
        from dataclasses import replace
        self._snap = replace(self._snap, out_hex=bytes(data).hex())

    def stop(self):
        with contextlib.suppress(Exception):
            self._source.close()
```

- [ ] **Step 4: Run → pass.** **Step 5: Commit** — `git add web/generic_poller.py tests/test_generic_poller.py && git commit -m "feat: GenericPoller + ParamSpec + GenericSource"`

---

### Task 4: BusController — modo generic

**Files:** Modify `web/controller.py`; Test `tests/test_controller.py`.

**Interfaces:** Consumes `web.generic_poller.ParamSpec`, `web.snapshot.idle_io_snapshot`. Produces no novo `BusController(..., make_generic=None)`; comandos `param_read(spec_dict)`, `set_output(hex)`, `stop_generic()`; leitura `io_snapshot() -> IoSnapshot`. `make_generic(settings, ParamSpec) -> GenericEngine`.

- [ ] **Step 1: Failing tests** (fakes)

```python
# tests/test_controller.py (acrescentar)
def _io(in_hex="", connected=True):
    from web.snapshot import IoSnapshot
    return IoSnapshot(active=True, address=9, connected=connected, diag="OK",
                      in_hex=in_hex, out_hex="", input_size=2, output_size=0,
                      rate_hz=0.0, ts=0.0)


class FakeGenericEngine:
    def __init__(self): self.out=None; self.stopped=False
    def step(self): return _io(in_hex="abcd")
    def snapshot(self): return _io(in_hex="abcd")
    def set_output(self, data): self.out=bytes(data)
    def stop(self): self.stopped=True


def make_ctrl_generic(**kw):
    made = {"exchange": [], "generic": []}
    def make_exchange(s, o): e=FakeEngine(offset=o); made["exchange"].append(e); return e
    def make_generic(s, spec): g=FakeGenericEngine(); made["generic"].append((spec, g)); return g
    from web.controller import BusController
    ctrl = BusController(make_exchange, lambda s: FakeProbe({}),
                         BusSettings(), addresses=[1,2], make_generic=make_generic)
    return ctrl, made


def _spec():
    return {"gsd": "ifm.gsd", "address": 9, "modules": ["Class 2 Multiturn"],
            "input_size": 2, "output_size": 0}


def test_param_read_enters_generic():
    ctrl, made = make_ctrl_generic()
    enc = made["exchange"][0]
    ctrl.param_read(_spec()); ctrl.step()
    assert enc.stopped is True
    assert ctrl.bus_snapshot().mode == "generic"
    assert ctrl.io_snapshot().in_hex == "abcd"
    assert made["generic"][-1][0].address == 9


def test_set_output_forwarded_in_generic():
    ctrl, made = make_ctrl_generic()
    ctrl.param_read(_spec()); ctrl.step()
    ctrl.set_output("00ff"); ctrl.step()
    assert made["generic"][-1][1].out == b"\x00\xff"


def test_stop_generic_returns_to_exchange():
    ctrl, made = make_ctrl_generic()
    ctrl.param_read(_spec()); ctrl.step()
    g = made["generic"][-1][1]
    ctrl.stop_generic(); ctrl.step()
    assert g.stopped is True and ctrl.bus_snapshot().mode == "exchange"
    assert ctrl.io_snapshot().active is False


def test_param_read_build_failure_goes_idle():
    def boom(s, spec): raise RuntimeError("sem GSD")
    from web.controller import BusController
    ctrl = BusController(lambda s,o: FakeEngine(), lambda s: FakeProbe({}),
                         BusSettings(), addresses=[1,2], make_generic=boom)
    ctrl.param_read(_spec()); ctrl.step()
    assert ctrl.bus_snapshot().mode == "idle"
    assert "erro" in ctrl.bus_snapshot().diag
```

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** em `web/controller.py`:
  - import: `from web.generic_poller import ParamSpec`; `from web.snapshot import IoSnapshot, idle_io_snapshot, initial_snapshot, Snapshot`.
  - `__init__(... , make_generic=None)`: guardar `self._make_generic=make_generic`; `self._generic=None`; `self._io_snap=idle_io_snapshot()`; `self._param=None`.
  - comandos (fila): `param_read(spec)`, `set_output(hex)`, `stop_generic()` → append `("param", spec)`, `("set_output", hex)`, `("stop_generic", None)`.
  - `io_snapshot()`: `with self._lock: return self._io_snap`.
  - em `step()` adicionar ramo: `elif self._mode == "generic" and self._generic is not None:` → `snap = self._generic.step(); self._io_working = snap`; e ao final publicar io (`_publish_io`). Quando não generic: `self._io_working = idle_io_snapshot(...)`. (Definir `_publish_io` análogo a `_publish_bus`.)
  - `_handle`: 
    ```python
    elif name == "param" : self._begin_generic(arg)
    elif name == "set_output":
        if self._mode == "generic" and self._generic is not None:
            try:
                raw = bytes.fromhex(arg or "")
            except ValueError:
                self._diag = "saída hex inválida"; return
            self._generic.set_output(raw)
    elif name == "stop_generic":
        if self._mode == "generic":
            self._teardown_generic(); self._start_exchange()
    ```
  - `_begin_generic(spec_dict)`:
    ```python
    if self._mode == "scanning":
        self._diag = "aguarde a varredura"; return
    try:
        spec = ParamSpec(gsd=str(spec_dict["gsd"]), address=int(spec_dict["address"]),
                         modules=tuple(spec_dict.get("modules", [])),
                         input_size=int(spec_dict["input_size"]),
                         output_size=int(spec_dict["output_size"]))
    except (KeyError, TypeError, ValueError) as e:
        self._diag = "parâmetros inválidos: %s" % e; return
    self._teardown_engine()
    try:
        self._generic = self._make_generic(self._settings, spec) if self._make_generic else None
        if self._generic is None:
            raise RuntimeError("generic não suportado")
        self._mode = "generic"; self._diag = "parametrizando"
    except Exception as e:
        self._generic = None; self._mode = "idle"
        self._diag = "erro ao parametrizar: %s" % e
    ```
  - `_teardown_generic()`: `if self._generic: stop(); self._generic=None`.
  - `_publish_io()`: monta sob lock `self._io_snap = self._io_working`.
  - garantir que `step()` sempre seta `self._io_working` (idle quando não generic) e chama `_publish_io()`.
  - `stop()` (ciclo): também `_teardown_generic()`.

(Implementação completa segue o padrão de `_begin_scan`/`_publish_bus` já existentes.)

- [ ] **Step 4: Run → pass.** **Step 5: Commit** — `git add web/controller.py tests/test_controller.py && git commit -m "feat: BusController modo generic (param_read/set_output/stop_generic)"`

---

### Task 5: server.py — comandos + io no /ws

**Files:** Modify `web/server.py`; Test `tests/test_server.py`.

- [ ] **Step 1: Failing tests** (acrescentar)

```python
def test_handle_param_read_set_output_stop():
    c = FakeController()
    handle_ws_message(c, json.dumps({"cmd": "param_read", "gsd": "x.gsd",
        "address": 9, "modules": ["m"], "input_size": 2, "output_size": 0}))
    handle_ws_message(c, json.dumps({"cmd": "set_output", "hex": "00ff"}))
    handle_ws_message(c, json.dumps({"cmd": "stop_generic"}))
    assert ("param", 9) in c.calls and ("set_output", "00ff") in c.calls and ("stop",) in c.calls
```
(estender o `FakeController` em test_server.py com `io_snapshot()`, `param_read(spec)`, `set_output(hex)`, `stop_generic()` gravando em `calls`.)

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** em `web/server.py`:
  - import `io_snapshot_to_dict`.
  - no `/ws` loop, após o `bus_snapshot`: `ws.send(json.dumps(io_snapshot_to_dict(controller.io_snapshot())))`.
  - em `handle_ws_message`:
    ```python
    elif cmd == "param_read":
        controller.param_read(data)
    elif cmd == "set_output":
        controller.set_output(data.get("hex", ""))
    elif cmd == "stop_generic":
        controller.stop_generic()
    ```
- [ ] **Step 4: Run → pass.** **Step 5: Commit** — `git add web/server.py tests/test_server.py && git commit -m "feat: server despacha param_read/set_output/stop_generic + io no /ws"`

---

### Task 6: serve.py — make_generic + wiring

**Files:** Modify `serve.py`.

- [ ] **Step 1:** Em `build_controller`, adicionar a factory e passá-la:

```python
    from profibus_amg11.generic import GenericDpMaster
    from web.generic_poller import GenericPoller

    def make_generic(s, spec):
        data = gsd_store.read(spec.gsd)          # FileNotFoundError/GsdInfoError sobe -> idle
        src = GenericDpMaster(conf_path, data, spec.address, list(spec.modules),
                              spec.input_size, spec.output_size,
                              baud=s.baud, master_addr=s.master_addr, sim=sim)
        return GenericPoller(src, spec.address, spec.input_size, spec.output_size)

    return BusController(make_exchange, make_probe, settings,
                         initial_offset=cfg.offset, addresses=addresses,
                         on_settings_saved=store.save, make_generic=make_generic)
```
Nota: `build_controller` precisa do `gsd_store` para a factory. Construir `gsd_store = GsdStore(ROOT/"gsd")` dentro de `build_controller` (e `main` reusa o mesmo via um parâmetro ou recria). Simplest: `build_controller(..., gsd_dir=ROOT/"gsd")` cria o store e o expõe; `main` passa o mesmo store ao `create_app`. Ajustar assinaturas conforme necessário, mantendo o teste de integração sim verde.

- [ ] **Step 2: Smoke** — `python serve.py --sim --port 8694 &`; `curl -s localhost:8694/ | grep -q 'id="app"'`; matar. Sem traceback.
- [ ] **Step 3: Full suite** — `pytest -q` verde.
- [ ] **Step 4: Commit** — `git add serve.py && git commit -m "feat: wiring make_generic no serve.py (lê GSD do store)"`

---

### Task 7: Frontend — "Parametrizar e ler" + painel I/O

**Files:** Modify `web/static/app.js`, `web/static/styles.css`; Test `tests/test_frontend_assets.py`.

- [ ] **Step 1: Failing tests** (acrescentar)

```python
def test_app_has_parameterize_and_io():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "Parametrizar e ler" in js
    assert "param_read" in js and "set_output" in js and "stop_generic" in js
    assert 'type === "io"' in js
```

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** em `web/static/app.js`:
  - `useBusSocket`: adicionar estado `io` (`useState({active:false,...})`) e rotear `else if (m.type === "io") setIo(m)`; retornar `io`.
  - `GsdView`: receber/usar `send` e `io`; adicionar, no bloco do `sel` (inspetor), campos de **endereço** + **tam. entrada** + **tam. saída** e botão **"Parametrizar e ler"** → `send({cmd:"param_read", gsd: sel.filename, address, modules: chosen, input_size, output_size})`.
  - Quando `io.active`: painel com estado/diag, `entrada (hex)` = `io.in_hex`, campo de saída + "Enviar saída" → `send({cmd:"set_output", hex})`, e "Parar" → `send({cmd:"stop_generic"})`.
  - `App`: passar `io` para `GsdView` (`useBusSocket` já devolve `io`).
- [ ] **Step 4: CSS** — reusar `.rows`/`.controls`/`.muted`/`.warn`; adicionar `.io-panel{border-top:1px solid var(--hair);padding-top:14px;display:flex;flex-direction:column;gap:12px}`.
- [ ] **Step 5: Run + full suite → verde.** Smoke visual em `--sim`.
- [ ] **Step 6: Commit** — `git add web/static/app.js web/static/styles.css tests/test_frontend_assets.py && git commit -m "feat: aba GSD parametriza escravo e mostra I/O cru ao vivo"`

---

## Self-Review

**Spec coverage:** GenericDpMaster/slave_desc → T1; IoSnapshot → T2; GenericPoller/ParamSpec/GenericSource → T3; modo generic + comandos → T4; WS io + dispatch → T5; make_generic wiring → T6; UI parametrizar + I/O → T7. ✓
**Placeholders:** T4 descreve a edição do controller em prosa+código-guia (padrão dos `_begin_scan`/`_publish_bus` existentes) — a implementação real segue esses padrões já no repo. Sem TBD. ✓
**Type consistency:** `ParamSpec`, `IoSnapshot`, `make_generic(settings, spec)`, `GenericSource`/`GenericEngine`, `io_snapshot()` coerentes entre T1–T7. ✓
