from web.poller import EncoderPoller
from fakes import FakeSource


class FakeClock:
    """Relógio injetável: retorna tempos sucessivos (sem tempo real)."""
    def __init__(self, times):
        self._times = list(times)
        self._i = 0

    def __call__(self):
        t = self._times[min(self._i, len(self._times) - 1)]
        self._i += 1
        return t


def test_step_updates_snapshot():
    p = EncoderPoller(FakeSource([0x0800]), period=8192, now=FakeClock([1.0, 2.0]))
    snap = p.step()
    assert snap.connected is True
    assert snap.raw == 0x0800
    assert abs(snap.angle_deg - 90.0) < 1e-6


def test_zero_command_zeroes_next_reading():
    p = EncoderPoller(FakeSource([0x0800]), period=8192, now=FakeClock([1.0, 2.0, 3.0]))
    p.step()                  # raw 2048
    p.zero()                  # enfileira
    snap = p.step()           # drena zero -> offset 2048 -> proxima leitura raw 0
    assert snap.raw == 0
    assert snap.offset == 0x0800


def test_clear_zero_resets_offset():
    p = EncoderPoller(FakeSource([0x0800]), period=8192, now=FakeClock([1, 2, 3, 4]))
    p.step(); p.zero(); p.step()
    p.clear_zero()
    snap = p.step()
    assert snap.offset == 0
    assert snap.raw == 0x0800


def test_rate_hz_uses_injected_clock():
    # leituras a cada 0.05s -> ~20 Hz
    p = EncoderPoller(FakeSource([0x0800, 0x0800]), period=8192,
                      now=FakeClock([1.00, 1.05, 1.10]))
    p.step()                  # primeira leitura: sem rate ainda
    snap = p.step()           # dt = 0.05 -> 20 Hz
    assert abs(snap.rate_hz - 20.0) < 1e-6


def test_no_reading_marks_stale():
    p = EncoderPoller(FakeSource([0x0800, None]), period=8192,
                      now=FakeClock([1.0, 5.0]), stale_after=0.5)
    p.step()                  # leitura ok
    snap = p.step()           # None, clock pulou 4s > stale_after
    assert snap.connected is False
    assert snap.diag == "sem leitura"


def test_stop_closes_source_without_start():
    src = FakeSource([0x0800])
    p = EncoderPoller(src, period=8192)
    p.stop()                  # sem start(): thread é None, só fecha a fonte
    assert src.closed is True
