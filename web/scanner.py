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
    """Varre uma lista de endereços, um por step(). Determinístico (relógio injetado)."""

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
