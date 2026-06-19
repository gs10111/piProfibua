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
