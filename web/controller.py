"""Dono único da serial: orquestra exchange e scan numa só thread.

Padrão do v1: a lógica vive em step(); a thread só chama step() em loop. O
estado de trabalho (mode/diag/settings/scan) é mutado apenas pela thread do
controller; o que a web lê é publicado como objeto imutável sob lock.
"""
from __future__ import annotations

import threading
import time
from typing import Protocol, runtime_checkable

from web.scanner import BusScan, BusSnapshot, ScanState
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
                 initial_offset=0, addresses=None, now=time.monotonic,
                 tick_sleep=0.005, on_settings_saved=None):
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
        self._offset = initial_offset

        self._encoder_snap = initial_snapshot(offset=initial_offset)
        self._bus_snap = BusSnapshot(self._mode, self._settings,
                                     self._scan_state, self._diag)
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
        saved_err = None
        if self._on_settings_saved is not None:
            try:
                self._on_settings_saved(new)
            except Exception as e:  # persistir não pode poluir o loop nem pular o rebuild
                saved_err = e
        if self._mode != "scanning":
            self._teardown_engine()
            self._start_exchange()
        # se scanning: o rebuild pós-scan usa self._settings (já atualizado)
        if saved_err is not None:
            self._diag = "settings aplicados, falha ao salvar: %s" % saved_err

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
