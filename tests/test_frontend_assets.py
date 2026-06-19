from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"


def test_vendor_modules_present_and_nonempty():
    for name in ("preact.module.js", "hooks.module.js", "htm.module.js"):
        f = STATIC / "vendor" / name
        assert f.exists() and f.stat().st_size > 1024, name


def test_index_uses_importmap_and_app_module():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'type="importmap"' in html
    assert '/vendor/preact.module.js' in html
    assert 'app.js' in html
    assert 'id="app"' in html


def test_app_js_uses_ws_and_zero_command():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "/ws" in js
    assert '"zero"' in js or "'zero'" in js


def test_styles_no_inter_default():
    import re
    css = (STATIC / "styles.css").read_text(encoding="utf-8").lower()
    # "Inter" banida como fonte default; \b evita falso-positivo em "pointer".
    assert re.search(r"\binter\b", css) is None   # nenhuma fonte "Inter"
