from pyprofibus.fdl import FdlTelegram, FdlTelegram_FdlStat_Con

from profibus_amg11.scan import FdlBusProbe, SimBusProbe, Station, StationType


class FakeClock:
    def __init__(self, times):
        self._t = list(times)
        self._i = 0

    def __call__(self):
        v = self._t[min(self._i, len(self._t) - 1)]
        self._i += 1
        return v


class FakeTransceiver:
    """Roteiriza respostas pelo destino sondado: addr -> FdlTelegram | None.

    delay = nº de polls que retornam None antes de entregar a resposta
    (simula a resposta chegando alguns polls depois do envio).
    """

    def __init__(self, replies, delay=0):
        self._replies = replies
        self._delay = delay
        self._polls = 0
        self.sent = []
        self._last_da = None

    def send(self, fcb, telegram):
        self._last_da = telegram.da
        self.sent.append(telegram.da)

    def poll(self, timeout):
        self._polls += 1
        if self._polls <= self._delay:
            return (False, None)
        tel = self._replies.get(self._last_da)
        return (tel is not None, tel)


def test_from_fc_maps_station_types():
    assert StationType.from_fc(FdlTelegram.FC_SLAVE) is StationType.SLAVE
    assert StationType.from_fc(FdlTelegram.FC_MNRDY) is StationType.MASTER_NOT_READY
    assert StationType.from_fc(FdlTelegram.FC_MRDY) is StationType.MASTER_READY
    assert StationType.from_fc(FdlTelegram.FC_MTR) is StationType.MASTER_IN_RING


def test_probe_returns_station_on_reply():
    reply = FdlTelegram_FdlStat_Con(da=2, sa=7,
                                    fc=FdlTelegram.FC_OK | FdlTelegram.FC_SLAVE)
    trans = FakeTransceiver({7: reply})
    probe = FdlBusProbe(trans, master_addr=2, timeout=0.01,
                        now=FakeClock([1.000, 1.005]))
    st = probe.probe(7)
    assert st is not None
    assert st.addr == 7 and st.station_type is StationType.SLAVE
    assert abs(st.response_ms - 5.0) < 1e-6


def test_probe_returns_none_on_silence():
    trans = FakeTransceiver({})
    probe = FdlBusProbe(trans, master_addr=2, timeout=0.05,
                        now=FakeClock([0.0, 1.0]))
    assert probe.probe(9) is None


def test_probe_ignores_reply_from_other_address():
    reply = FdlTelegram_FdlStat_Con(da=2, sa=99,
                                    fc=FdlTelegram.FC_OK | FdlTelegram.FC_SLAVE)
    trans = FakeTransceiver({7: reply})
    probe = FdlBusProbe(trans, master_addr=2, timeout=0.05,
                        now=FakeClock([0.0, 1.0]))
    assert probe.probe(7) is None


def test_probe_polls_until_reply_arrives():
    # A resposta chega no 2º poll: o laço tem que continuar pollando até o deadline.
    reply = FdlTelegram_FdlStat_Con(da=2, sa=7,
                                    fc=FdlTelegram.FC_OK | FdlTelegram.FC_SLAVE)
    trans = FakeTransceiver({7: reply}, delay=1)
    probe = FdlBusProbe(trans, master_addr=2, timeout=0.05,
                        now=FakeClock([0.0, 0.01, 0.02]))
    st = probe.probe(7)
    assert st is not None and st.addr == 7


def test_sim_probe_finds_listed_addrs():
    probe = SimBusProbe(found_addrs=[3])
    assert probe.probe(3).station_type is StationType.SLAVE
    assert probe.probe(4) is None
