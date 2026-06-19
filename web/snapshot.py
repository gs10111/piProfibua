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
