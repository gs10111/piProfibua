from web.generic_poller import GenericPoller


class FakeClock:
    def __init__(self, t):
        self._t = list(t)
        self._i = 0

    def __call__(self):
        v = self._t[min(self._i, len(self._t) - 1)]
        self._i += 1
        return v


class FakeGenericSource:
    def __init__(self, seq, connected=True):
        self._seq = list(seq)
        self._i = 0
        self._connected = connected
        self.out = None
        self.closed = False

    def poll(self):
        v = self._seq[min(self._i, len(self._seq) - 1)]
        self._i += 1
        return v

    def set_output(self, data):
        self.out = bytes(data)

    @property
    def connected(self):
        return self._connected

    @property
    def diag(self):
        return "OK" if self._connected else "conectando"

    def close(self):
        self.closed = True


def test_step_reads_input():
    p = GenericPoller(FakeGenericSource([b"\x12\x34"]), 9, 2, 0,
                      now=FakeClock([1.0, 2.0]))
    s = p.step()
    assert s.active and s.connected and s.in_hex == "1234" and s.address == 9


def test_rate_from_clock():
    p = GenericPoller(FakeGenericSource([b"\x00", b"\x00"]), 9, 1, 0,
                      now=FakeClock([1.00, 1.05, 1.10]))
    p.step()
    s = p.step()
    assert abs(s.rate_hz - 20.0) < 1e-6


def test_set_output_forwarded():
    src = FakeGenericSource([None])
    p = GenericPoller(src, 9, 0, 1)
    p.set_output(b"\xff")
    assert src.out == b"\xff" and p.snapshot().out_hex == "ff"


def test_stale_when_no_reading():
    p = GenericPoller(FakeGenericSource([b"\x00", None], connected=True), 9, 1, 0,
                      now=FakeClock([1.0, 5.0]), stale_after=0.5)
    p.step()
    s = p.step()
    assert s.diag == "sem leitura"


def test_stop_closes_source():
    src = FakeGenericSource([None])
    GenericPoller(src, 9, 0, 0).stop()
    assert src.closed is True
