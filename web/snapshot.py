"""Estado publicado pelo poller + serialização pura (testável isolada)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    angle_deg: float
    raw: int
    raw_max: int
    bytes_hex: str
    offset: int
    connected: bool
    rate_hz: float
    diag: str
    ts: float


def initial_snapshot(offset: int = 0, raw_max: int = 0) -> Snapshot:
    return Snapshot(angle_deg=0.0, raw=0, raw_max=raw_max, bytes_hex="", offset=offset,
                    connected=False, rate_hz=0.0, diag="conectando", ts=0.0)


def snapshot_to_dict(s: Snapshot) -> dict:
    return {
        "type": "reading",
        "angle_deg": round(s.angle_deg, 3),
        "raw": s.raw,
        "raw_max": s.raw_max,
        "bytes_hex": s.bytes_hex,
        "offset": s.offset,
        "connected": s.connected,
        "rate_hz": round(s.rate_hz, 1),
        "diag": s.diag,
        "ts": s.ts,
    }


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


def bus_snapshot_to_dict(bus) -> dict:
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
