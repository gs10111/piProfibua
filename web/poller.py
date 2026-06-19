"""Serviço de aplicação: thread dona do ReadingSource, mantém um Snapshot vivo."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

from web.snapshot import Snapshot, initial_snapshot


class EncoderPoller:
    def __init__(self, source, period, initial_offset=0,
                 now=time.monotonic, stale_after=0.5, tick_sleep=0.005):
        self._source = source
        self._period = period
        self._offset = initial_offset
        self._now = now
        self._stale_after = stale_after
        self._tick_sleep = tick_sleep

        self._lock = threading.Lock()
        self._snap = initial_snapshot(offset=initial_offset)
        self._last_raw = 0
        self._last_rx = None      # tempo da última leitura válida
        self._rate = 0.0
        self._pending = []        # fila de comandos
        self._thread = None
        self._running = False

    # --- API de comandos (chamada pela thread web) ---
    def zero(self):
        with self._lock:
            self._pending.append("zero")

    def clear_zero(self):
        with self._lock:
            self._pending.append("clear_zero")

    def snapshot(self):
        with self._lock:
            return self._snap

    # --- núcleo determinístico (testável sem thread) ---
    def step(self):
        with self._lock:
            cmds, self._pending = self._pending, []
        for c in cmds:
            if c == "zero":
                self._offset = (self._last_raw + self._offset) % self._period
                self._source.set_offset(self._offset)
            elif c == "clear_zero":
                self._offset = 0
                self._source.set_offset(0)

        reading = self._source.poll()
        now = self._now()

        if reading is not None:
            if self._last_rx is not None:
                dt = now - self._last_rx
                if dt > 0:
                    inst = 1.0 / dt
                    self._rate = inst if self._rate == 0.0 else 0.8 * self._rate + 0.2 * inst
            self._last_rx = now
            self._last_raw = reading.raw
            snap = Snapshot(angle_deg=reading.angle_deg, raw=reading.raw,
                            bytes_hex=reading.bytes_hex, offset=self._offset,
                            connected=True, rate_hz=self._rate, diag="OK", ts=now)
        else:
            connected = self._last_rx is not None and (now - self._last_rx) < self._stale_after
            prev = self._snap
            snap = replace(prev, offset=self._offset, connected=connected,
                           rate_hz=self._rate if connected else 0.0,
                           diag="OK" if connected else "sem leitura", ts=now)

        with self._lock:
            self._snap = snap
        return snap

    # --- ciclo de vida da thread ---
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            try:
                self.step()
            except Exception as e:  # nunca derruba a thread; reporta no snapshot
                with self._lock:
                    self._snap = replace(self._snap, connected=False,
                                         diag="erro: %s" % e, ts=self._now())
                time.sleep(0.2)
                continue
            if self._tick_sleep:
                time.sleep(self._tick_sleep)

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._source.close()
