# Explorador de Barramento — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar varredura de barramento (live list) e controles de baud/endereço do mestre (persistidos) ao app, introduzindo um `BusController` que é o dono único da serial com modos (exchange/scanning/idle).

**Architecture:** Um `BusController` (uma thread, padrão publish-snapshot-imutável do v1) orquestra um motor de exchange (o `EncoderPoller` v1, atrás de um Protocol) e um scan FDL passo-a-passo. Só um dono da serial por vez: ao varrer, derruba o exchange, abre a probe, varre, recria o exchange. Factories injetadas tornam tudo testável sem hardware.

**Tech Stack:** Python 3.12, pyprofibus (FDL: `FdlTelegram_FdlStat_Req`), Flask + flask-sock, Preact + htm vendorizados, pytest.

## Global Constraints

- **Sem libs novas.** Flask, flask-sock, Preact/htm já existem. Frontend sem build (vendorizado).
- **Dono único da serial:** scan e exchange nunca abrem a porta ao mesmo tempo.
- **Determinismo testável:** lógica em `step()`; relógio e factories injetados; **sem `sleep` em teste**; **sem hardware** (fakes).
- **Honestidade de baud:** UI permite escolher, mas só 9600/19200 são confiáveis no Pi não-RT; o resto é best-effort, marcado e avisado. Nunca prometer mais.
- **Princípios de frontend v1:** tema escuro de instrumento, acento único, **mono nos numerais/endereços**, **sem emoji**, contraste AA, foco visível, `prefers-reduced-motion`, copy direta (sem em-dash, sem frase de efeito), **Inter banido como default**.
- **Os 44 testes do v1 seguem verdes.**
- **`config/bus.json` é runtime → entra no `.gitignore`.**
- Commits em PT, terminando com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: BusSettings + SettingsStore (persistência em bus.json)

**Files:**
- Create: `web/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `ALLOWED_BAUDS: tuple[int,...]`, `RELIABLE_BAUDS=(9600,19200)`; `BusSettings(baud:int=19200, master_addr:int=1)` (frozen, valida em `__post_init__`); `SettingsStore(path)` com `load(defaults: BusSettings) -> BusSettings` e `save(settings: BusSettings) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settings.py
import pytest
from web.settings import BusSettings, SettingsStore, ALLOWED_BAUDS


def test_valid_settings():
    s = BusSettings(baud=19200, master_addr=3)
    assert s.baud == 19200 and s.master_addr == 3


def test_invalid_baud_rejected():
    with pytest.raises(ValueError):
        BusSettings(baud=12345, master_addr=1)


def test_invalid_master_addr_rejected():
    with pytest.raises(ValueError):
        BusSettings(baud=19200, master_addr=0)
    with pytest.raises(ValueError):
        BusSettings(baud=19200, master_addr=127)


def test_load_without_file_returns_defaults(tmp_path):
    store = SettingsStore(tmp_path / "bus.json")
    d = BusSettings(baud=9600, master_addr=2)
    assert store.load(d) == d


def test_save_then_load_roundtrip(tmp_path):
    store = SettingsStore(tmp_path / "bus.json")
    s = BusSettings(baud=93750, master_addr=5)
    store.save(s)
    assert store.load(BusSettings()) == s


def test_corrupt_or_out_of_range_file_falls_back_to_defaults(tmp_path):
    p = tmp_path / "bus.json"
    p.write_text('{"baud": 999, "master_addr": 5}', encoding="utf-8")
    d = BusSettings(baud=19200, master_addr=1)
    assert SettingsStore(p).load(d) == d
    p.write_text("not json", encoding="utf-8")
    assert SettingsStore(p).load(d) == d
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_settings.py -q` → FAIL (no module).

- [ ] **Step 3: Implement**

```python
# web/settings.py
"""Configurações de barramento (baud + endereço do mestre) com persistência."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Conjunto padrão PROFIBUS oferecido na UI.
ALLOWED_BAUDS = (9600, 19200, 45450, 93750, 187500, 500000, 1500000)
# Bauds confiáveis no Pi não-RT via pyprofibus; o resto é best-effort.
RELIABLE_BAUDS = (9600, 19200)


@dataclass(frozen=True)
class BusSettings:
    baud: int = 19200
    master_addr: int = 1

    def __post_init__(self):
        if self.baud not in ALLOWED_BAUDS:
            raise ValueError("baud %r não permitido" % (self.baud,))
        if not (1 <= self.master_addr <= 126):
            raise ValueError("master_addr deve estar entre 1 e 126")


class SettingsStore:
    """Lê/grava BusSettings num JSON. Valores inválidos caem no default."""

    def __init__(self, path):
        self._path = Path(path)

    def load(self, defaults: BusSettings) -> BusSettings:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return BusSettings(baud=int(data["baud"]),
                               master_addr=int(data["master_addr"]))
        except (FileNotFoundError, ValueError, TypeError, KeyError):
            return defaults

    def save(self, settings: BusSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"baud": settings.baud,
                        "master_addr": settings.master_addr}),
            encoding="utf-8")
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/test_settings.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add web/settings.py tests/test_settings.py && git commit -m "feat: BusSettings + SettingsStore (persistência bus.json)"`

---

### Task 2: Scan domain — StationType, Station, BusProbe, FdlBusProbe, SimBusProbe

**Files:**
- Create: `profibus_amg11/scan.py`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes: pyprofibus `pyprofibus.fdl` (`FdlTelegram`, `FdlFCB`, `FdlTelegram_FdlStat_Req`, `FdlTransceiver`).
- Produces: `StationType` (enum, `.from_fc(fc:int)`), `Station(addr:int, station_type:StationType, response_ms:float)` (frozen), `BusProbe` (Protocol: `probe(addr:int)->Station|None`, `close()->None`), `FdlBusProbe(transceiver, master_addr, timeout=0.05, now=time.monotonic, phy=None)`, `SimBusProbe(found_addrs, now=time.monotonic)`.

- [ ] **Step 1: Write the failing tests** (fake transceiver — sem serial)

```python
# tests/test_scan.py
from profibus_amg11.scan import (StationType, Station, FdlBusProbe, SimBusProbe)
from pyprofibus.fdl import FdlTelegram, FdlTelegram_FdlStat_Con


class FakeClock:
    def __init__(self, times):
        self._t = list(times); self._i = 0
    def __call__(self):
        v = self._t[min(self._i, len(self._t) - 1)]; self._i += 1; return v


class FakeTransceiver:
    """Roteiriza respostas por endereço: addr -> FdlTelegram | None."""
    def __init__(self, replies):
        self._replies = replies; self.sent = []
    def send(self, fcb, telegram):
        self.sent.append(telegram.da)
        self._last_da = telegram.da
    def poll(self, timeout):
        tel = self._replies.get(self._last_da)
        return (tel is not None, tel)


def test_from_fc_maps_station_types():
    assert StationType.from_fc(FdlTelegram.FC_SLAVE) is StationType.SLAVE
    assert StationType.from_fc(FdlTelegram.FC_MNRDY) is StationType.MASTER_NOT_READY
    assert StationType.from_fc(FdlTelegram.FC_MRDY) is StationType.MASTER_READY
    assert StationType.from_fc(FdlTelegram.FC_MTR) is StationType.MASTER_IN_RING


def test_probe_returns_station_on_reply():
    reply = FdlTelegram_FdlStat_Con(da=2, sa=7,
                                    fc=FdlTelegram.FC_OK | FdlTelegram.FC_SLAVE)
    trans = FakeTransceiver({7: reply})
    probe = FdlBusProbe(trans, master_addr=2, timeout=0.01,
                        now=FakeClock([1.000, 1.005]))
    st = probe.probe(7)
    assert st is not None
    assert st.addr == 7 and st.station_type is StationType.SLAVE
    assert abs(st.response_ms - 5.0) < 1e-6


def test_probe_returns_none_on_silence():
    trans = FakeTransceiver({})  # ninguém responde
    probe = FdlBusProbe(trans, master_addr=2)
    assert probe.probe(9) is None


def test_probe_ignores_reply_from_other_address():
    reply = FdlTelegram_FdlStat_Con(da=2, sa=99,
                                    fc=FdlTelegram.FC_OK | FdlTelegram.FC_SLAVE)
    trans = FakeTransceiver({7: reply})
    probe = FdlBusProbe(trans, master_addr=2)
    assert probe.probe(7) is None  # sa != addr sondado


def test_sim_probe_finds_listed_addrs():
    probe = SimBusProbe(found_addrs=[3])
    assert probe.probe(3).station_type is StationType.SLAVE
    assert probe.probe(4) is None
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_scan.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# profibus_amg11/scan.py
"""Varredura de barramento (live list) via FDL Request-FDL-Status."""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from pyprofibus.fdl import (FdlTelegram, FdlFCB, FdlTelegram_FdlStat_Req)


class StationType(enum.Enum):
    SLAVE = "slave"
    MASTER_NOT_READY = "master_not_ready"
    MASTER_READY = "master_ready"
    MASTER_IN_RING = "master_in_ring"
    UNKNOWN = "unknown"

    @classmethod
    def from_fc(cls, fc: int) -> "StationType":
        return {
            FdlTelegram.FC_SLAVE: cls.SLAVE,
            FdlTelegram.FC_MNRDY: cls.MASTER_NOT_READY,
            FdlTelegram.FC_MRDY: cls.MASTER_READY,
            FdlTelegram.FC_MTR: cls.MASTER_IN_RING,
        }.get(fc & FdlTelegram.FC_STYPE_MASK, cls.UNKNOWN)


@dataclass(frozen=True)
class Station:
    addr: int
    station_type: StationType
    response_ms: float


@runtime_checkable
class BusProbe(Protocol):
    def probe(self, addr: int) -> Optional[Station]: ...
    def close(self) -> None: ...


class FdlBusProbe:
    """Probe FDL real: Request-FDL-Status + leitura da resposta."""

    def __init__(self, transceiver, master_addr, timeout=0.05,
                 now=time.monotonic, phy=None):
        self._trans = transceiver
        self._master_addr = master_addr
        self._timeout = timeout
        self._now = now
        self._phy = phy

    def probe(self, addr):
        req = FdlTelegram_FdlStat_Req(da=addr, sa=self._master_addr)
        start = self._now()
        self._trans.send(FdlFCB(enable=False), req)
        ok, tel = self._trans.poll(self._timeout)
        if not ok or tel is None or tel.sa is None:
            return None
        if (tel.sa & FdlTelegram.ADDRESS_MASK) != addr:
            return None
        return Station(addr=addr,
                       station_type=StationType.from_fc(tel.fc or 0),
                       response_ms=(self._now() - start) * 1000.0)

    def close(self):
        if self._phy is not None:
            self._phy.close()


class SimBusProbe:
    """Probe sem hardware: reporta SLAVE nos endereços listados (para --sim)."""

    def __init__(self, found_addrs, now=time.monotonic):
        self._found = set(found_addrs)
        self._now = now

    def probe(self, addr):
        if addr in self._found:
            return Station(addr=addr, station_type=StationType.SLAVE,
                           response_ms=1.0)
        return None

    def close(self):
        pass
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/test_scan.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add profibus_amg11/scan.py tests/test_scan.py && git commit -m "feat: domínio de scan FDL (StationType, Station, FdlBusProbe, SimBusProbe)"`

---

### Task 3: BusScan (passo-a-passo) + ScanState + BusSnapshot

**Files:**
- Create: `web/scanner.py`
- Test: `tests/test_scanner.py`

**Interfaces:**
- Consumes: `profibus_amg11.scan.Station`; `web.settings.BusSettings`.
- Produces: `ScanState(status="idle", current_addr=None, scanned=0, total=0, found=(), started_ts=None, done_ts=None, error=None)` (frozen); `BusScan(probe, addresses, now=time.monotonic)` com `.step()->ScanState`, propriedade `.done`, `.state()`; `BusSnapshot(mode:str, settings:BusSettings, scan_state:ScanState, diag:str)` (frozen).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scanner.py
from web.scanner import BusScan, ScanState
from profibus_amg11.scan import Station, StationType


class FakeClock:
    def __init__(self, times):
        self._t = list(times); self._i = 0
    def __call__(self):
        v = self._t[min(self._i, len(self._t) - 1)]; self._i += 1; return v


class FakeProbe:
    """addr -> Station|None, roteirizado."""
    def __init__(self, hits):
        self._hits = hits; self.closed = False
    def probe(self, addr):
        return self._hits.get(addr)
    def close(self):
        self.closed = True


def _slave(a):
    return Station(addr=a, station_type=StationType.SLAVE, response_ms=2.0)


def test_scan_progresses_and_finds():
    probe = FakeProbe({4: _slave(4)})
    scan = BusScan(probe, [3, 4, 5], now=FakeClock([10, 11, 12, 13]))
    s = scan.step()                 # sonda 3 (nada)
    assert s.status == "scanning" and s.scanned == 1 and s.current_addr == 4
    scan.step()                     # sonda 4 (hit)
    s = scan.step()                 # sonda 5 (nada) -> done
    assert scan.done is True
    assert s.status == "done" and s.scanned == 3 and s.total == 3
    assert [st.addr for st in s.found] == [4]


def test_scan_sets_timestamps():
    scan = BusScan(FakeProbe({}), [1], now=FakeClock([100.0, 105.0]))
    scan.step()
    s = scan.state()
    assert s.started_ts == 100.0 and s.done_ts == 105.0


def test_empty_addresses_is_done_immediately():
    scan = BusScan(FakeProbe({}), [], now=FakeClock([1.0]))
    assert scan.done is True
    s = scan.step()
    assert s.status == "done" and s.total == 0
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_scanner.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# web/scanner.py
"""Lógica pura de varredura, passo-a-passo (sem pyprofibus, sem sleep)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple

from profibus_amg11.scan import Station
from web.settings import BusSettings


@dataclass(frozen=True)
class ScanState:
    status: str = "idle"            # idle | scanning | done
    current_addr: Optional[int] = None
    scanned: int = 0
    total: int = 0
    found: Tuple[Station, ...] = ()
    started_ts: Optional[float] = None
    done_ts: Optional[float] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class BusSnapshot:
    mode: str
    settings: BusSettings
    scan_state: ScanState
    diag: str = "ok"


class BusScan:
    def __init__(self, probe, addresses, now=time.monotonic):
        self._probe = probe
        self._addresses = list(addresses)
        self._now = now
        self._i = 0
        self._found = []
        self._started = None
        self._done_ts = None

    @property
    def done(self):
        return self._i >= len(self._addresses)

    def step(self) -> ScanState:
        if self._started is None:
            self._started = self._now()
        if not self.done:
            station = self._probe.probe(self._addresses[self._i])
            if station is not None:
                self._found.append(station)
            self._i += 1
        if self.done and self._done_ts is None:
            self._done_ts = self._now()
        return self.state()

    def state(self) -> ScanState:
        if self._started is None:
            status = "idle"
        elif self.done:
            status = "done"
        else:
            status = "scanning"
        current = None if self.done else self._addresses[self._i]
        return ScanState(status=status, current_addr=current,
                         scanned=self._i, total=len(self._addresses),
                         found=tuple(self._found),
                         started_ts=self._started, done_ts=self._done_ts)
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/test_scanner.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add web/scanner.py tests/test_scanner.py && git commit -m "feat: BusScan passo-a-passo + ScanState/BusSnapshot"`

---

### Task 4: BusController (dono único da serial, modos)

**Files:**
- Create: `web/controller.py`
- Test: `tests/test_controller.py`

**Interfaces:**
- Consumes: `web.scanner` (`BusScan`, `ScanState`, `BusSnapshot`); `web.snapshot` (`Snapshot`, `initial_snapshot`); `web.settings.BusSettings`.
- Produces: `ExchangeEngine` (Protocol: `step()->Snapshot`, `snapshot()->Snapshot`, `zero()`, `clear_zero()`, `stop()`); `BusController(make_exchange, make_probe, settings, *, addresses=None, now=time.monotonic, tick_sleep=0.005, on_settings_saved=None)` com comandos `scan()`, `apply_settings(baud, master_addr)`, `zero()`, `clear_zero()`; leituras `encoder_snapshot()->Snapshot`, `bus_snapshot()->BusSnapshot`; núcleo `step()`; ciclo `start()`, `stop()`. `make_exchange(settings, offset)`; `make_probe(settings)`.

- [ ] **Step 1: Write the failing tests** (fakes — sem hardware, sem thread)

```python
# tests/test_controller.py
from web.controller import BusController
from web.snapshot import Snapshot, initial_snapshot
from web.settings import BusSettings
from profibus_amg11.scan import Station, StationType


def _snap(offset=0, connected=True):
    return Snapshot(angle_deg=0.0, raw=0, raw_max=8191, bytes_hex="",
                    offset=offset, connected=connected, rate_hz=0.0,
                    diag="OK", ts=0.0)


class FakeEngine:
    def __init__(self, offset=0):
        self._offset = offset; self.zeroed = 0; self.cleared = 0; self.stopped = False
    def step(self):
        return _snap(offset=self._offset)
    def snapshot(self):
        return _snap(offset=self._offset)
    def zero(self):
        self.zeroed += 1
    def clear_zero(self):
        self.cleared += 1
    def stop(self):
        self.stopped = True


class FakeProbe:
    def __init__(self, hits):
        self._hits = hits; self.closed = False
    def probe(self, addr):
        return self._hits.get(addr)
    def close(self):
        self.closed = True


def make_ctrl(**kw):
    made = {"exchange": [], "probe": []}
    def make_exchange(settings, offset):
        e = FakeEngine(offset=offset); made["exchange"].append((settings, offset, e)); return e
    def make_probe(settings):
        p = kw.get("probe") or FakeProbe({}); made["probe"].append((settings, p)); return p
    saved = []
    ctrl = BusController(make_exchange, make_probe,
                         kw.get("settings", BusSettings(baud=19200, master_addr=1)),
                         addresses=kw.get("addresses", [1, 2, 3]),
                         on_settings_saved=saved.append)
    return ctrl, made, saved


def test_starts_in_exchange_and_updates_encoder():
    ctrl, made, _ = make_ctrl()
    ctrl.step()
    assert ctrl.bus_snapshot().mode == "exchange"
    assert ctrl.encoder_snapshot().connected is True
    assert len(made["exchange"]) == 1


def test_scan_pauses_exchange_runs_and_resumes():
    probe = FakeProbe({3: Station(3, StationType.SLAVE, 2.0)})
    ctrl, made, _ = make_ctrl(probe=probe, addresses=[1, 2, 3])
    first_engine = made["exchange"][0][2]
    ctrl.scan()
    # drena comando -> derruba engine, abre probe, entra scanning
    ctrl.step()
    assert first_engine.stopped is True
    assert ctrl.bus_snapshot().mode == "scanning"
    # endereços = [2, 3] (pula o master_addr=1); 2 passos
    ctrl.step(); ctrl.step()
    bs = ctrl.bus_snapshot()
    assert bs.mode == "exchange"                      # resumiu
    assert [s.addr for s in bs.scan_state.found] == [3]
    assert probe.closed is True
    assert len(made["exchange"]) == 2                 # recriou o engine


def test_apply_settings_persists_and_rebuilds():
    ctrl, made, saved = make_ctrl()
    ctrl.apply_settings(9600, 4)
    ctrl.step()
    assert saved == [BusSettings(baud=9600, master_addr=4)]
    assert ctrl.bus_snapshot().settings == BusSettings(baud=9600, master_addr=4)
    assert made["exchange"][-1][0] == BusSettings(baud=9600, master_addr=4)


def test_apply_invalid_settings_rejected():
    ctrl, made, saved = make_ctrl()
    n = len(made["exchange"])
    ctrl.apply_settings(99999, 1)        # baud inválido
    ctrl.step()
    assert saved == []
    assert "inválida" in ctrl.bus_snapshot().diag
    assert len(made["exchange"]) == n    # não recriou


def test_exchange_build_failure_goes_idle_without_crash():
    def boom(settings, offset):
        raise RuntimeError("sem serial")
    ctrl = BusController(boom, lambda s: FakeProbe({}),
                         BusSettings(), addresses=[1, 2])
    ctrl.step()
    assert ctrl.bus_snapshot().mode == "idle"
    assert "erro" in ctrl.bus_snapshot().diag


def test_zero_forwarded_to_engine():
    ctrl, made, _ = make_ctrl()
    ctrl.zero(); ctrl.step()
    assert made["exchange"][0][2].zeroed == 1


def test_offset_preserved_across_rebuild():
    ctrl, made, _ = make_ctrl(probe=FakeProbe({}), addresses=[1, 2])
    made["exchange"][0][2]._offset = 1234     # engine reporta offset
    ctrl.step()                               # controller lê offset do snapshot
    ctrl.scan(); ctrl.step()                  # scanning (addrs=[2])
    ctrl.step()                               # done -> recria engine
    assert made["exchange"][-1][1] == 1234    # offset repassado ao novo engine
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_controller.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# web/controller.py
"""Dono único da serial: orquestra exchange e scan numa só thread.

Padrão do v1: a lógica vive em step(); a thread só chama step() em loop.
Estado de trabalho (mode/diag/settings/scan) é mutado só pela thread do
controller; o que a web lê é publicado como objeto imutável sob lock.
"""
from __future__ import annotations

import threading
import time
from typing import Optional, Protocol, runtime_checkable

from web.scanner import BusScan, ScanState, BusSnapshot
from web.settings import BusSettings
from web.snapshot import Snapshot, initial_snapshot


@runtime_checkable
class ExchangeEngine(Protocol):
    def step(self) -> Snapshot: ...
    def snapshot(self) -> Snapshot: ...
    def zero(self) -> None: ...
    def clear_zero(self) -> None: ...
    def stop(self) -> None: ...


class BusController:
    def __init__(self, make_exchange, make_probe, settings, *,
                 addresses=None, now=time.monotonic, tick_sleep=0.005,
                 on_settings_saved=None):
        self._make_exchange = make_exchange
        self._make_probe = make_probe
        self._settings = settings
        self._addresses = list(addresses) if addresses is not None else list(range(127))
        self._now = now
        self._tick_sleep = tick_sleep
        self._on_settings_saved = on_settings_saved

        self._lock = threading.Lock()
        self._pending = []
        self._mode = "exchange"
        self._diag = "ok"
        self._engine = None
        self._scan = None
        self._probe = None
        self._scan_state = ScanState()
        self._offset = 0

        self._encoder_snap = initial_snapshot()
        self._bus_snap = BusSnapshot(self._mode, self._settings, self._scan_state, self._diag)
        self._thread = None
        self._running = False

        self._start_exchange()
        self._publish_bus()

    # ---- comandos (thread web) ----
    def scan(self):
        with self._lock:
            self._pending.append(("scan", None))

    def apply_settings(self, baud, master_addr):
        with self._lock:
            self._pending.append(("apply", (baud, master_addr)))

    def zero(self):
        with self._lock:
            self._pending.append(("zero", None))

    def clear_zero(self):
        with self._lock:
            self._pending.append(("clear_zero", None))

    # ---- leituras (thread web) ----
    def encoder_snapshot(self) -> Snapshot:
        with self._lock:
            return self._encoder_snap

    def bus_snapshot(self) -> BusSnapshot:
        with self._lock:
            return self._bus_snap

    # ---- núcleo determinístico ----
    def step(self):
        with self._lock:
            cmds, self._pending = self._pending, []
        for name, arg in cmds:
            self._handle(name, arg)

        if self._mode == "scanning":
            self._scan_step()
        elif self._mode == "exchange" and self._engine is not None:
            snap = self._engine.step()
            self._offset = snap.offset
            with self._lock:
                self._encoder_snap = snap
        self._publish_bus()

    # ---- helpers (só thread do controller) ----
    def _publish_bus(self):
        bus = BusSnapshot(self._mode, self._settings, self._scan_state, self._diag)
        with self._lock:
            self._bus_snap = bus

    def _handle(self, name, arg):
        if name == "zero" and self._engine is not None:
            self._engine.zero()
        elif name == "clear_zero" and self._engine is not None:
            self._engine.clear_zero()
        elif name == "apply":
            self._apply(arg[0], arg[1])
        elif name == "scan":
            self._begin_scan()

    def _start_exchange(self):
        try:
            self._engine = self._make_exchange(self._settings, self._offset)
            self._mode = "exchange"
            self._diag = "ok"
        except Exception as e:
            self._engine = None
            self._mode = "idle"
            self._diag = "erro ao iniciar: %s" % e

    def _teardown_engine(self):
        if self._engine is not None:
            try:
                self._offset = self._engine.snapshot().offset
            except Exception:
                pass
            try:
                self._engine.stop()
            except Exception:
                pass
            self._engine = None

    def _apply(self, baud, master_addr):
        try:
            new = BusSettings(baud=baud, master_addr=master_addr)
        except (ValueError, TypeError) as e:
            self._diag = "config inválida: %s" % e
            return
        self._settings = new
        if self._on_settings_saved is not None:
            self._on_settings_saved(new)
        if self._mode != "scanning":
            self._teardown_engine()
            self._start_exchange()
        # se scanning: o rebuild pós-scan usa self._settings (novo) automaticamente

    def _begin_scan(self):
        if self._mode == "scanning":
            return
        self._teardown_engine()
        try:
            self._probe = self._make_probe(self._settings)
        except Exception as e:
            self._probe = None
            self._scan_state = ScanState(status="done",
                                         error="erro ao abrir: %s" % e,
                                         done_ts=self._now())
            self._start_exchange()
            return
        addrs = [a for a in self._addresses if a != self._settings.master_addr]
        self._scan = BusScan(self._probe, addrs, now=self._now)
        self._mode = "scanning"
        self._diag = "varrendo"

    def _scan_step(self):
        self._scan_state = self._scan.step()
        if self._scan.done:
            if self._probe is not None:
                try:
                    self._probe.close()
                except Exception:
                    pass
                self._probe = None
            self._scan = None
            self._start_exchange()

    # ---- ciclo da thread ----
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            try:
                self.step()
            except Exception as e:
                self._diag = "erro: %s" % e
                self._publish_bus()
                time.sleep(0.2)
                continue
            if self._tick_sleep:
                time.sleep(self._tick_sleep)

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._teardown_engine()
        if self._probe is not None:
            try:
                self._probe.close()
            except Exception:
                pass
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/test_controller.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add web/controller.py tests/test_controller.py && git commit -m "feat: BusController (dono único da serial, modos exchange/scan/idle)"`

---

### Task 5: Serialização do bus + handler de comandos no server

**Files:**
- Modify: `web/snapshot.py` (adicionar `bus_snapshot_to_dict`)
- Modify: `web/server.py` (`create_app(controller)`; `handle_ws_message`; /ws com 2 tipos)
- Test: `tests/test_snapshot.py` (adicionar), `tests/test_server.py` (substituir pela versão controller)

**Interfaces:**
- Consumes: `BusSnapshot` (de `web.scanner`); `BusController` (duck-typed nos testes).
- Produces: `bus_snapshot_to_dict(bus: BusSnapshot) -> dict`; `handle_ws_message(controller, raw: str) -> None`; `create_app(controller) -> Flask`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_snapshot.py  (acrescentar)
from web.snapshot import bus_snapshot_to_dict
from web.scanner import BusSnapshot, ScanState
from web.settings import BusSettings
from profibus_amg11.scan import Station, StationType


def test_bus_snapshot_to_dict_shape():
    bs = BusSnapshot(
        mode="scanning",
        settings=BusSettings(baud=19200, master_addr=2),
        scan_state=ScanState(status="scanning", current_addr=5, scanned=3,
                             total=10, found=(Station(4, StationType.SLAVE, 2.345),)),
        diag="varrendo")
    d = bus_snapshot_to_dict(bs)
    assert d["type"] == "bus"
    assert d["mode"] == "scanning"
    assert d["settings"] == {"baud": 19200, "master_addr": 2}
    assert d["scan"]["status"] == "scanning"
    assert d["scan"]["current_addr"] == 5
    assert d["scan"]["scanned"] == 3 and d["scan"]["total"] == 10
    assert d["scan"]["found"] == [
        {"addr": 4, "station_type": "slave", "response_ms": 2.35}]
```

```python
# tests/test_server.py  (substituir conteúdo)
import json
from web.server import create_app, handle_ws_message
from web.snapshot import initial_snapshot
from web.scanner import BusSnapshot, ScanState
from web.settings import BusSettings


class FakeController:
    def __init__(self):
        self.calls = []
    def encoder_snapshot(self):
        return initial_snapshot()
    def bus_snapshot(self):
        return BusSnapshot("exchange", BusSettings(), ScanState(), "ok")
    def zero(self): self.calls.append(("zero",))
    def clear_zero(self): self.calls.append(("clear_zero",))
    def scan(self): self.calls.append(("scan",))
    def apply_settings(self, b, m): self.calls.append(("apply", b, m))


def test_index_served():
    app = create_app(FakeController())
    client = app.test_client()
    assert client.get("/").status_code == 200


def test_handle_zero_and_scan():
    c = FakeController()
    handle_ws_message(c, json.dumps({"cmd": "zero"}))
    handle_ws_message(c, json.dumps({"cmd": "scan"}))
    assert c.calls == [("zero",), ("scan",)]


def test_handle_apply_settings():
    c = FakeController()
    handle_ws_message(c, json.dumps({"cmd": "apply_settings", "baud": 9600, "master_addr": 3}))
    assert c.calls == [("apply", 9600, 3)]


def test_handle_invalid_messages_ignored():
    c = FakeController()
    handle_ws_message(c, "not json")
    handle_ws_message(c, json.dumps({"cmd": "apply_settings", "baud": "x"}))
    handle_ws_message(c, json.dumps({"nope": 1}))
    assert c.calls == []
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_snapshot.py tests/test_server.py -q` → FAIL.

- [ ] **Step 3: Implement `bus_snapshot_to_dict` em `web/snapshot.py`** (acrescentar ao fim)

```python
def bus_snapshot_to_dict(bus):
    """Serializa o BusSnapshot para o contrato JSON do WebSocket (type=bus)."""
    s = bus.scan_state
    return {
        "type": "bus",
        "mode": bus.mode,
        "diag": bus.diag,
        "settings": {"baud": bus.settings.baud,
                     "master_addr": bus.settings.master_addr},
        "scan": {
            "status": s.status,
            "current_addr": s.current_addr,
            "scanned": s.scanned,
            "total": s.total,
            "error": s.error,
            "found": [{"addr": st.addr,
                       "station_type": st.station_type.value,
                       "response_ms": round(st.response_ms, 2)}
                      for st in s.found],
        },
    }
```

- [ ] **Step 4: Reescrever `web/server.py`**

```python
"""Transporte: Flask serve estáticos e um WebSocket com encoder + barramento."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, send_from_directory
from flask_sock import Sock

from web.snapshot import snapshot_to_dict, bus_snapshot_to_dict

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
```

- [ ] **Step 5: Run to verify pass + full suite** — `.venv/bin/python -m pytest tests/test_snapshot.py tests/test_server.py -q` → PASS.

- [ ] **Step 6: Commit** — `git add web/snapshot.py web/server.py tests/test_snapshot.py tests/test_server.py && git commit -m "feat: serialização bus + handler de comandos (scan/apply) no server"`

---

### Task 6: Wiring — master overrides, serve.py, .gitignore

**Files:**
- Modify: `profibus_amg11/master.py` (overrides `baud`/`master_addr`; `build_scan_phy`)
- Modify: `serve.py` (SettingsStore + BusController + factories)
- Modify: `.gitignore` (+`config/bus.json`)
- Test: `tests/test_master_overrides.py` (novo)

**Interfaces:**
- Consumes: `Amg11Master`, `EncoderPoller`, `BusController`, `SettingsStore`, `FdlBusProbe`/`SimBusProbe`, `FdlTransceiver`.
- Produces: `Amg11Master(conf_path, encoder_cfg, sim=False, debug=False, baud=None, master_addr=None)`; `build_scan_phy(conf_path, baud)`; `default_settings_from_conf(conf_path) -> BusSettings`.

- [ ] **Step 1: Write the failing test** (override afeta o conf, em sim)

```python
# tests/test_master_overrides.py
from pathlib import Path
from profibus_amg11.master import Amg11Master, build_scan_phy
from profibus_amg11.config import EncoderConfig

CONF = str(Path(__file__).resolve().parent.parent / "config" / "amg11.conf")


def test_master_applies_baud_and_addr_override_in_sim():
    m = Amg11Master(CONF, EncoderConfig(), sim=True, baud=93750, master_addr=5)
    try:
        assert m.master.masterAddr == 5
    finally:
        m.close()


def test_build_scan_phy_uses_given_baud():
    phy = build_scan_phy(CONF, 9600)   # phyType=serial no conf -> abriria a serial
    try:
        assert phy is not None
    finally:
        phy.close()
```

Nota: `test_build_scan_phy_uses_given_baud` abre `/dev/serial0`; se a porta não existir no ambiente, **marcar para pular**:
```python
import pytest, serial
def test_build_scan_phy_uses_given_baud():
    try:
        phy = build_scan_phy(CONF, 9600)
    except (serial.SerialException, FileNotFoundError, OSError):
        pytest.skip("sem porta serial neste ambiente")
    try:
        assert phy is not None
    finally:
        phy.close()
```

- [ ] **Step 2: Run to verify it fails** — `.venv/bin/python -m pytest tests/test_master_overrides.py -q` → FAIL (TypeError: baud).

- [ ] **Step 3: Implement em `profibus_amg11/master.py`**

Editar `__init__` para aceitar overrides (após `conf = PbConf.fromFile(...)`, antes de `makeDPM`):
```python
    def __init__(self, conf_path, encoder_cfg, sim=False, debug=False,
                 baud=None, master_addr=None):
        ...
        with _chdir(project_root):
            conf = PbConf.fromFile(str(conf_path))
            if sim:
                conf.phyType = "dummyslave"
            if baud is not None:
                conf.phyBaud = baud
            if master_addr is not None:
                conf.dpMasterAddr = master_addr
            conf.debug = 2 if debug else 0
            self.master = conf.makeDPM()
```
E acrescentar no fim do módulo:
```python
def build_scan_phy(conf_path, baud):
    """Cria uma PHY avulsa (no baud dado) para varredura FDL. Chama .close()."""
    conf_path = Path(conf_path).resolve()
    project_root = conf_path.parent.parent
    with _chdir(project_root):
        conf = PbConf.fromFile(str(conf_path))
        conf.phyBaud = baud
        return conf.makePhy()
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/test_master_overrides.py -q` → PASS (o teste de phy pode pular sem hardware).

- [ ] **Step 5: Reescrever `serve.py`**

```python
#!/usr/bin/env python3
"""Sobe o app web do mestre PROFIBUS: dashboard do encoder + explorador de barramento."""
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
    cp = configparser.ConfigParser()
    cp.read(conf_path)
    baud = cp.getint("PHY", "baud", fallback=19200)
    master = cp.getint("DP", "master_addr", fallback=1)
    if baud not in ALLOWED_BAUDS:
        baud = 19200
    if not (1 <= master <= 126):
        master = 1
    return BusSettings(baud=baud, master_addr=master)


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
            # Sem barramento real: demonstra o scan achando o escravo configurado.
            slave_addr = default_slave_addr(args.conf)
            return SimBusProbe(found_addrs=[slave_addr] if slave_addr else [])
        phy = build_scan_phy(args.conf, s.baud)
        return FdlBusProbe(FdlTransceiver(phy), master_addr=s.master_addr, phy=phy)

    controller = BusController(make_exchange, make_probe, settings,
                              on_settings_saved=store.save)
    controller.start()
    try:
        app = create_app(controller)
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        controller.stop()


def default_slave_addr(conf_path):
    cp = configparser.ConfigParser()
    cp.read(conf_path)
    for sec in cp.sections():
        if sec.startswith("SLAVE_"):
            try:
                return cp.getint(sec, "addr")
            except (configparser.NoOptionError, ValueError):
                pass
    return None


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Add `config/bus.json` ao `.gitignore`** (acrescentar a linha `config/bus.json`).

- [ ] **Step 7: Smoke test em sim** — `timeout 4 .venv/bin/python serve.py --sim --port 8699 &` depois `curl -s localhost:8699/ | grep -q "<div id=\"app\">" && echo OK`; matar o processo. Esperado: `OK` e sem traceback.

- [ ] **Step 8: Run full suite** — `.venv/bin/python -m pytest -q` → todos verdes.

- [ ] **Step 9: Commit** — `git add profibus_amg11/master.py serve.py .gitignore tests/test_master_overrides.py && git commit -m "feat: wiring do BusController no serve.py + overrides de baud/endereço"`

---

### Task 7: Frontend — shell com abas + vista Barramento

**Files:**
- Modify: `web/static/app.js` (shell + `EncoderView` extraída + `BusView`)
- Modify: `web/static/styles.css` (abas, controles, tabela, progresso, aviso)
- Test: `tests/test_static.py` (novo — asserções no fonte estático, padrão do v1)

**Interfaces:**
- Consumes: contrato WS (`type:"reading"` e `type:"bus"`); comandos `{cmd:"scan"}`, `{cmd:"apply_settings",baud,master_addr}`.

- [ ] **Step 1: Write the failing test** (asserções no fonte; sem runtime JS)

```python
# tests/test_static.py
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")

EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿]")


def test_routes_by_message_type():
    assert 'type === "reading"' in APP and 'type === "bus"' in APP


def test_has_both_views_and_tabs():
    assert "Barramento" in APP and "Encoder" in APP
    assert "Varrer" in APP


def test_sends_scan_and_apply_commands():
    assert 'cmd: "scan"' in APP or "cmd:'scan'" in APP or '"scan"' in APP
    assert "apply_settings" in APP


def test_honest_baud_warning_present():
    assert "best-effort" in APP
    assert "9600" in APP and "19200" in APP


def test_no_emoji_in_ui():
    assert EMOJI.search(APP) is None


def test_no_inter_font_default():
    assert re.search(r"\binter\b", CSS, re.IGNORECASE) is None
```

- [ ] **Step 2: Run to verify they fail** — `.venv/bin/python -m pytest tests/test_static.py -q` → FAIL.

- [ ] **Step 3: Reescrever `web/static/app.js`**

```javascript
import { h, render } from "preact";
import { useState, useEffect, useRef } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

const BAUDS = [9600, 19200, 45450, 93750, 187500, 500000, 1500000];
const RELIABLE = [9600, 19200];

function useBusSocket() {
  const [encoder, setEncoder] = useState({ connected: false, diag: "conectando",
    angle_deg: 0, raw: 0, raw_max: 8191, bytes_hex: "", offset: 0, rate_hz: 0 });
  const [bus, setBus] = useState({ mode: "exchange", diag: "ok",
    settings: { baud: 19200, master_addr: 1 },
    scan: { status: "idle", current_addr: null, scanned: 0, total: 0, found: [] } });
  const ws = useRef(null);
  useEffect(() => {
    let stop = false;
    function connect() {
      if (stop) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const s = new WebSocket(`${proto}://${location.host}/ws`);
      ws.current = s;
      s.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.type === "reading") setEncoder(m);
        else if (m.type === "bus") setBus(m);
      };
      s.onclose = () => { if (!stop) setTimeout(connect, 800); };
    }
    connect();
    return () => { stop = true; ws.current && ws.current.close(); };
  }, []);
  const send = (obj) => ws.current && ws.current.readyState === 1 &&
    ws.current.send(JSON.stringify(obj));
  return { encoder, bus, send };
}

function EncoderView({ snap, send }) {
  const live = snap.connected;
  const angle = Number(snap.angle_deg || 0);
  return html`
    <div class="view">
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
        <div>bruto <b>${snap.raw} / ${snap.raw_max}</b></div>
        <div>bytes <b>${snap.bytes_hex || "--"}</b></div>
        <div>offset <b>${snap.offset}</b></div>
        <div>diag <b>${snap.diag}</b></div>
      </div>
      <div class="actions">
        <button onClick=${() => send({ cmd: "zero" })}>Zerar aqui</button>
        <button class="ghost" onClick=${() => send({ cmd: "clear_zero" })}>Desfazer</button>
      </div>
    </div>`;
}

function BusView({ bus, send }) {
  const s = bus.scan || {};
  const scanning = bus.mode === "scanning" || s.status === "scanning";
  const [baud, setBaud] = useState(bus.settings.baud);
  const [addr, setAddr] = useState(bus.settings.master_addr);
  useEffect(() => { setBaud(bus.settings.baud); setAddr(bus.settings.master_addr); },
    [bus.settings.baud, bus.settings.master_addr]);
  const pct = s.total ? Math.round((100 * s.scanned) / s.total) : 0;
  const found = s.found || [];
  return html`
    <div class="view">
      <div class="controls">
        <label>Baud
          <select value=${baud} onChange=${(e) => setBaud(Number(e.target.value))}>
            ${BAUDS.map((b) => html`<option value=${b}>${b}${RELIABLE.includes(b) ? "" : " (best-effort)"}</option>`)}
          </select>
        </label>
        <label>Endereço do mestre
          <input type="number" min="1" max="126" value=${addr}
                 onInput=${(e) => setAddr(Number(e.target.value))} />
        </label>
        <button onClick=${() => send({ cmd: "apply_settings", baud, master_addr: addr })}>Aplicar</button>
      </div>
      ${!RELIABLE.includes(baud) ? html`<p class="warn">No Raspberry Pi (Linux não-RT) via pyprofibus, só 9600 e 19200 são confiáveis. Acima disso o timing de slot tende a falhar (best-effort).</p>` : ""}
      <div class="scanbar">
        <button onClick=${() => send({ cmd: "scan" })} disabled=${scanning}>
          ${scanning ? "Varrendo..." : "Varrer"}</button>
        ${scanning ? html`<div class="prog"><div class="bar" style=${`width:${pct}%`}></div></div>
          <span class="muted">${s.scanned}/${s.total}${s.current_addr != null ? ` · addr ${s.current_addr}` : ""}</span>` : ""}
      </div>
      <table class="stations">
        <thead><tr><th>Endereço</th><th>Tipo</th><th>ms</th></tr></thead>
        <tbody>
          ${found.map((st) => html`<tr><td>${st.addr}</td><td>${st.station_type}</td><td>${st.response_ms}</td></tr>`)}
        </tbody>
      </table>
      ${s.status === "done" && found.length === 0 ? html`<p class="muted">Nenhuma estação respondeu.</p>` : ""}
      ${s.status === "idle" ? html`<p class="muted">Ainda não varrido.</p>` : ""}
      ${bus.diag && bus.diag !== "ok" ? html`<p class="warn">${bus.diag}</p>` : ""}
    </div>`;
}

function App() {
  const { encoder, bus, send } = useBusSocket();
  const [tab, setTab] = useState("encoder");
  return html`
    <div class="panel">
      <nav class="tabs">
        <button class=${"tab" + (tab === "encoder" ? " active" : "")}
                onClick=${() => setTab("encoder")}>Encoder</button>
        <button class=${"tab" + (tab === "bus" ? " active" : "")}
                onClick=${() => setTab("bus")}>Barramento</button>
      </nav>
      ${tab === "encoder"
        ? html`<${EncoderView} snap=${encoder} send=${send} />`
        : html`<${BusView} bus=${bus} send=${send} />`}
    </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
```

- [ ] **Step 4: Acrescentar CSS em `web/static/styles.css`** (tokens já existem; adicionar componentes)

```css
/* abas */
.tabs { display: flex; gap: 0.25rem; margin-bottom: 1rem; }
.tab { background: transparent; border: 1px solid var(--line, #233);
  color: var(--muted, #9bb); padding: 0.4rem 0.9rem; border-radius: 8px;
  cursor: pointer; font: inherit; }
.tab.active { color: var(--fg, #eef); border-color: var(--accent, #34d399);
  background: rgba(52, 211, 153, 0.08); }
.tab:focus-visible { outline: 2px solid var(--accent, #34d399); outline-offset: 2px; }

.view { display: flex; flex-direction: column; gap: 1rem; }

/* controles de baud/endereço */
.controls { display: flex; flex-wrap: wrap; gap: 1rem; align-items: end; }
.controls label { display: flex; flex-direction: column; gap: 0.3rem;
  font-size: 0.8rem; color: var(--muted, #9bb); }
.controls select, .controls input { background: var(--bg2, #0e1a1a);
  color: var(--fg, #eef); border: 1px solid var(--line, #233);
  border-radius: 8px; padding: 0.4rem 0.6rem; font: inherit;
  font-family: var(--mono, ui-monospace, monospace); }
.controls button, .scanbar button { background: var(--accent, #34d399);
  color: #04211a; border: 0; border-radius: 8px; padding: 0.5rem 1rem;
  font: inherit; font-weight: 600; cursor: pointer; }
.scanbar button:disabled { opacity: 0.5; cursor: default; }

.warn { color: #f6c177; font-size: 0.82rem; line-height: 1.4;
  border-left: 2px solid #f6c177; padding-left: 0.6rem; margin: 0; }

/* progresso */
.scanbar { display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap; }
.prog { flex: 1; min-width: 120px; height: 6px; background: var(--line, #233);
  border-radius: 3px; overflow: hidden; }
.prog .bar { height: 100%; background: var(--accent, #34d399);
  transition: width 0.2s linear; }
@media (prefers-reduced-motion: reduce) { .prog .bar { transition: none; } }
.muted { color: var(--muted, #9bb); font-size: 0.82rem; }

/* tabela de estações */
.stations { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.stations th, .stations td { text-align: left; padding: 0.4rem 0.6rem;
  border-bottom: 1px solid var(--line, #233); }
.stations th { color: var(--muted, #9bb); font-weight: 600; font-size: 0.78rem;
  text-transform: uppercase; letter-spacing: 0.04em; }
.stations td { font-family: var(--mono, ui-monospace, monospace); }
```

- [ ] **Step 5: Run static asserts + full suite** — `.venv/bin/python -m pytest -q` → todos verdes.

- [ ] **Step 6: Smoke test visual em sim** — subir `serve.py --sim --port 8699`, abrir no navegador, conferir as duas abas, clicar Varrer (deve achar o escravo simulado), trocar baud para um best-effort (aviso aparece). Matar o processo.

- [ ] **Step 7: Commit** — `git add web/static/app.js web/static/styles.css tests/test_static.py && git commit -m "feat: frontend com abas Encoder/Barramento + varredura e controles"`

---

## Self-Review

**1. Spec coverage:**
- §2 BusController/modos → Task 4. Varredura live list → Tasks 2+3+4. Controles baud/endereço + persistência → Tasks 1+6+7. Duas vistas → Task 7. ✓
- §3 verdade técnica (FDL, makePhy, close) → Tasks 2 (FdlBusProbe) + 6 (build_scan_phy). ✓
- §5 troca de dono + preservar zero → Task 4 (`_teardown_engine`/`_start_exchange` + offset). ✓
- §6 varredura (faixa, pula master, timeout, progresso) → Tasks 3+4. ✓
- §7 baud honesto + persistência → Tasks 1 (validação), 7 (aviso), 6 (bus.json). ✓
- §8 contrato WS (2 tipos + comandos) → Task 5. ✓
- §9 frontend princípios → Task 7 (test_static cobre sem-emoji, sem-Inter, aviso honesto). ✓
- §10 erros (probe falha, rebuild falha, apply inválido) → Task 4 tests. ✓
- §11 testes TDD → cada task. ✓

**2. Placeholder scan:** sem TBD/TODO; todo passo tem código real. ✓

**3. Type consistency:** `BusSnapshot(mode, settings, scan_state, diag)` consistente entre scanner/controller/snapshot/server. `make_exchange(settings, offset)` e `make_probe(settings)` idem. `Station(addr, station_type, response_ms)` idem. `ScanState` campos idem. ✓
