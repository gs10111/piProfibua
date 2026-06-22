from profibus_amg11.scan import Station, StationType
from web.scanner import BusScan, ScanState


class FakeClock:
    def __init__(self, times):
        self._t = list(times)
        self._i = 0

    def __call__(self):
        v = self._t[min(self._i, len(self._t) - 1)]
        self._i += 1
        return v


class FakeProbe:
    def __init__(self, hits):
        self._hits = hits
        self.closed = False

    def probe(self, addr):
        return self._hits.get(addr)

    def close(self):
        self.closed = True


def _slave(a):
    return Station(addr=a, station_type=StationType.SLAVE, response_ms=2.0)


def test_scan_progresses_and_finds():
    probe = FakeProbe({4: _slave(4)})
    scan = BusScan(probe, [3, 4, 5], now=FakeClock([10, 11, 12, 13]))
    s = scan.step()                 # sonda 3 (nada)
    assert s.status == "scanning" and s.scanned == 1 and s.current_addr == 4
    scan.step()                     # sonda 4 (hit)
    s = scan.step()                 # sonda 5 (nada) -> done
    assert scan.done is True
    assert s.status == "done" and s.scanned == 3 and s.total == 3
    assert [st.addr for st in s.found] == [4]


def test_scan_sets_timestamps():
    scan = BusScan(FakeProbe({}), [1], now=FakeClock([100.0, 105.0]))
    scan.step()
    s = scan.state()
    assert s.started_ts == 100.0 and s.done_ts == 105.0


def test_empty_addresses_is_done_immediately():
    scan = BusScan(FakeProbe({}), [], now=FakeClock([1.0]))
    assert scan.done is True
    s = scan.step()
    assert s.status == "done" and s.total == 0


def test_scan_state_defaults_are_idle():
    assert ScanState().status == "idle" and ScanState().scanned == 0
