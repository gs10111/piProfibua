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
