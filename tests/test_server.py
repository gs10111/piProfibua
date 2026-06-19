from web.server import create_app
from web.poller import EncoderPoller
from fakes import FakeSource


def make_app():
    poller = EncoderPoller(FakeSource([0x0800]), period=8192)
    poller.step()  # popula um snapshot
    return create_app(poller)


def test_index_served():
    app = make_app()
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'id="app"' in resp.data


def test_static_styles_route_is_clean():
    # styles.css só chega na Task 5; aqui garantimos que a app não quebra na rota.
    app = make_app()
    client = app.test_client()
    resp = client.get("/styles.css")
    assert resp.status_code in (200, 404)
