"""Màn hình HUD kiểu JARVIS: một trang web chạy ngay trên máy, hiện trạng thái của trợ lý.

Python mở một máy chủ nhỏ ở 127.0.0.1 (chỉ máy này truy cập được). Trang hud/index.html
hỏi /state vài lần mỗi giây để vẽ vòng sáng, và gửi lệnh về /command khi bấm nút.
"""

from __future__ import annotations

import atexit
import json
import mimetypes
import secrets
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

import psutil

import config as cfg
import learn
import market
from common import (CACHE, CHROMIUM_BROWSERS, HERE, WINDOWS, assistant_name, find_browser, lang,
                    launch, log, open_with_system, run)

PAGE = HERE / "hud" / "index.html"
LOG_LINES = 8


class NoHud:
    """Dùng khi tắt HUD: nhận lệnh nhưng không làm gì."""

    def set(self, **changes) -> None:
        pass


class Hud:
    def __init__(self, ears, on_command: Callable[[str], None]) -> None:
        self.ears = ears                 # vật có .level và .hearing (micro)
        self.on_command = on_command
        self.token = secrets.token_urlsafe(16)
        self.session = secrets.token_hex(4)   # đổi mỗi lần bật trợ lý: tab HUD cũ biết để tải lại
        self.last_poll = 0.0
        self.port = cfg.HUD_PORT
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        background = HERE / cfg.HUD_BACKGROUND if cfg.HUD_BACKGROUND else None
        self.background = background if background and background.is_file() else None
        self._state = {"status": "idle", "heard": "", "reply": "", "log": []}
        self._lock = threading.Lock()
        self._stats: dict = {}
        self._stats_at = 0.0
        self._net = (psutil.net_io_counters(), time.monotonic())
        psutil.cpu_percent(None)   # lần đo đầu luôn ra 0, đo mồi trước

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), _handler(self))
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.port}/"
        if cfg.HUD_MARKETS:
            market.start_background()

    # --- trạng thái -------------------------------------------------------
    def set(self, **changes) -> None:
        with self._lock:
            for key, who in (("heard", "Bạn"), ("reply", assistant_name())):
                if changes.get(key) and changes[key] != self._state[key]:
                    self._state["log"] = (self._state["log"] + [[who, changes[key]]])[-LOG_LINES:]
            self._state.update(changes)

    def snapshot(self) -> dict:
        with self._lock:
            state = dict(self._state)
        state.update(
            level=float(getattr(self.ears, "level", 0.0)),
            problem=getattr(self.ears, "problem", ""),
            hearing=bool(getattr(self.ears, "hearing", False)),
            name=assistant_name(),
            names=cfg.NAMES,
            lang=lang(),
            session=self.session,
            buttons=list(cfg.HUD_BUTTONS.items()),
            genres=list(cfg.HUD_GENRES.items()),
            learned=learn.counts(),
            background=self.background is not None,
            sys=self._system_stats(),
            **(market.hud_latest() if cfg.HUD_MARKETS else {}),
        )
        return state

    def _system_stats(self) -> dict:
        now = time.monotonic()
        if now - self._stats_at < 1.0:
            return self._stats
        net, then = psutil.net_io_counters(), self._net
        seconds = max(now - then[1], 1e-3)
        battery = psutil.sensors_battery()
        self._stats = {
            "cpu": round(psutil.cpu_percent(None)),
            "ram": round(psutil.virtual_memory().percent),
            "disk_free": round(psutil.disk_usage(Path.home().anchor).free / 1e9),
            "battery": round(battery.percent) if battery else None,
            "plugged": bool(battery and battery.power_plugged),
            "up": round((net.bytes_sent - then[0].bytes_sent) / seconds / 1024),
            "down": round((net.bytes_recv - then[0].bytes_recv) / seconds / 1024),
            "ip": _local_ip(),
        }
        self._net, self._stats_at = (net, now), now
        return self._stats

    # --- cửa sổ -----------------------------------------------------------
    def open_window(self) -> None:
        browser = cfg.HUD_BROWSER.strip()
        if WINDOWS and any(k in browser.lower() for k in CHROMIUM_BROWSERS):
            self._open_windows_app_window(browser)
            return
        if "chrome" in browser.lower():
            self._open_chrome_app()
            return
        # Tab HUD của lần chạy trước (nếu còn mở) sẽ tự kết nối lại; khi đó khỏi mở thêm tab.
        time.sleep(2.5)
        if time.monotonic() - self.last_poll < 2.5:
            log("🖥  Dùng lại tab HUD đang mở.")
            return
        if WINDOWS:
            open_with_system(self.url)
        elif not (browser and run(["open", "-a", browser, self.url])):
            run(["open", self.url])

    def _chrome_args(self, profile) -> list[str]:
        # hồ sơ riêng để Chrome chịu mở toàn màn hình
        args = [f"--user-data-dir={profile}", f"--app={self.url}", "--no-first-run",
                "--no-default-browser-check"]
        return args + (["--start-fullscreen"] if cfg.HUD_FULLSCREEN else [])

    def _open_chrome_app(self) -> None:
        """Mở HUD trong một cửa sổ Chrome riêng, toàn màn hình, không thanh địa chỉ."""
        profile = CACHE / "hud-chrome"
        if not run(["open", "-na", "Google Chrome", "--args", *self._chrome_args(profile)]):
            run(["open", self.url])
            return
        atexit.register(run, ["pkill", "-f", f"user-data-dir={profile}"])

    def _open_windows_app_window(self, browser: str) -> None:
        """Windows: như trên, với Chrome (hoặc Edge, Brave) cài trên máy."""
        exe = find_browser(browser)
        proc = exe and launch([exe, *self._chrome_args(CACHE / "hud-chrome")])
        if not proc:
            log(f"⚠️  Không mở được HUD bằng “{browser}”, dùng trình duyệt mặc định.")
            open_with_system(self.url)
            return
        # Tắt trợ lý thì đóng luôn cửa sổ HUD (cả các tiến trình con của trình duyệt).
        atexit.register(subprocess.run, ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        capture_output=True)

    def page(self) -> bytes:
        return PAGE.read_text(encoding="utf-8").replace("__TOKEN__", self.token).encode()


def start(ears, on_command: Callable[[str], None], open_window: bool = True):
    """Bật HUD nếu config cho phép; lỗi (vd trùng cổng) thì chạy tiếp không có HUD."""
    if not cfg.HUD:
        return NoHud()
    try:
        hud = Hud(ears, on_command)
    except OSError as e:
        log(f"⚠️  Không mở được HUD ở cổng {cfg.HUD_PORT}: {e}")
        return NoHud()
    log(f"🖥  HUD: {hud.url}")
    if open_window:
        hud.open_window()
    return hud


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # UDP không gửi gì đi, chỉ để hỏi địa chỉ
            return s.getsockname()[0]
    except OSError:
        return "—"


def _handler(hud: Hud):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:   # trang hỏi liên tục, đừng in ra màn hình
            pass

        def _allowed(self) -> bool:
            # Chặn trang web lạ mượn tên miền trỏ về máy này (DNS rebinding).
            return self.headers.get("Host") in hud.hosts

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if not self._allowed():
                self.send_error(403)
            elif self.path == "/":
                self._send(hud.page(), "text/html; charset=utf-8")
            elif self.path == "/state":
                hud.last_poll = time.monotonic()
                self._send(json.dumps(hud.snapshot(), ensure_ascii=False).encode(),
                           "application/json")
            elif self.path == "/background" and hud.background:
                kind = mimetypes.guess_type(hud.background.name)[0] or "image/webp"
                self._send(hud.background.read_bytes(), kind)
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            # Mã bí mật nằm trong trang HUD; trang web khác không đọc được nên không ra lệnh được.
            if (self.path != "/command" or not self._allowed()
                    or self.headers.get("X-Tom-Token") != hud.token):
                self.send_error(403)
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                text = str(json.loads(self.rfile.read(min(length, 4000)))["text"]).strip()
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
                return
            self._send(b"{}", "application/json")
            if text:
                threading.Thread(target=hud.on_command, args=(text,), daemon=True).start()

    return Handler
