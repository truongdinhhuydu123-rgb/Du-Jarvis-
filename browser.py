"""Một tab duy nhất: mọi trang trợ lý mở (YouTube, Facebook, Google...) đều hiện trong cùng một
tab của một cửa sổ Chrome riêng, thay vì mở thêm tab/cửa sổ làm nặng máy.

Cửa sổ này dùng hồ sơ Chrome riêng (.cache/browser) và mở cổng điều khiển nội bộ
127.0.0.1:BROWSER_PORT (giao thức DevTools của Chrome) để trợ lý đổi trang trong tab đó.
Chrome không cho điều khiển hồ sơ chính của bạn kiểu này, nên lần đầu cần đăng nhập
YouTube/Facebook trong cửa sổ này một lần.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

import config as cfg
from common import CACHE, find_browser, launch, log, open_with_system

PROFILE = CACHE / "browser"


def _api(path: str, method: str = "GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{cfg.BROWSER_PORT}{path}", method=method)
    with urllib.request.urlopen(req, timeout=2) as r:
        body = r.read()
    return json.loads(body) if body.strip().startswith((b"[", b"{")) else body


def _tabs() -> list[dict] | None:
    """Các tab đang mở trong cửa sổ của trợ lý; None nếu cửa sổ chưa chạy."""
    try:
        items = _api("/json/list")
    except OSError:
        return None
    return [t for t in items if t.get("type") == "page" and not t.get("url", "").startswith("devtools")]


def _navigate(tab: dict, url: str) -> None:
    from websockets.sync.client import connect

    with connect(tab["webSocketDebuggerUrl"], open_timeout=3, max_size=None) as ws:
        ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
        ws.recv(timeout=5)


def open_url(url: str, dry_run: bool = False) -> bool:
    """Mở url trong tab duy nhất của trợ lý (mở cửa sổ mới nếu chưa có)."""
    if dry_run:
        print("   $ [1 tab]", url)
        return True
    tabs = _tabs()
    if tabs is None:   # cửa sổ chưa chạy (hoặc bạn đã đóng): mở mới với đúng trang này
        exe = find_browser(cfg.BROWSER)
        if exe and launch([exe, f"--user-data-dir={PROFILE}",
                           f"--remote-debugging-port={cfg.BROWSER_PORT}",
                           "--no-first-run", "--no-default-browser-check", "--start-maximized", url]):
            return True
        log("⚠️  Không mở được cửa sổ riêng, dùng trình duyệt mặc định.")
        return open_with_system(url)
    try:
        if not tabs:   # cửa sổ còn chạy nhưng không còn tab nào
            _api("/json/new?" + urllib.parse.quote(url, safe=":/?&=%#+@,;~!$'()*"), method="PUT")
            return True
        keep, *extra = tabs
        _navigate(keep, url)
        for tab in extra:   # chỉ giữ một tab
            _api(f"/json/close/{tab['id']}")
        _api(f"/json/activate/{keep['id']}")   # đưa tab (và cửa sổ) lên trước
        return True
    except Exception as e:   # cổng bị chiếm, Chrome đổi giao thức... -> mở kiểu thường
        log(f"⚠️  Không điều khiển được tab ({e}); dùng trình duyệt mặc định.")
        return open_with_system(url)
