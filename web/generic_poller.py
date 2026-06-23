"""Motor do modo generic: mantém um IoSnapshot vivo lendo um GenericSource."""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, replace
from typing import Optional, Protocol, Tuple, runtime_checkable

from web.snapshot import IoSnapshot, idle_io_snapshot


@dataclass(frozen=True)
class ParamSpec:
    gsd: str
    address: int
    modules: Tuple[str, ...]   # tamanhos de I/O são derivados do GSD, não informados


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
    """Lê um GenericSource e mantém um IoSnapshot. Lógica em step() (testável)."""

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
        self._snap = replace(self._snap, out_hex=bytes(data).hex())

    def stop(self):
        with contextlib.suppress(Exception):
            self._source.close()
