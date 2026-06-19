"""Varredura de barramento (live list) via FDL Request-FDL-Status.

O pyprofibus não tem um scan pronto; construímos sobre o FDL. Para cada
endereço enviamos um Request-FDL-Status e quem responder está vivo. O byte
FC da resposta diz o tipo de estação (escravo / mestre / mestre no anel).
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from pyprofibus.fdl import FdlTelegram, FdlFCB, FdlTelegram_FdlStat_Req


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
    """Probe FDL real: envia Request-FDL-Status e lê a resposta de um endereço."""

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
    """Probe sem hardware (para --sim): reporta SLAVE nos endereços listados."""

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
