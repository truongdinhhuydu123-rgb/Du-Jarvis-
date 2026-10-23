"""Những việc trợ lý làm được trên máy: mở web, mở app, mở nhạc, tìm file, workflow buổi sáng."""

from __future__ import annotations

import functools
import json
import os
import random
import re
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import browser
import config as cfg
import voice
from common import (CACHE, CHROMIUM_BROWSERS, MAC, WINDOWS, assistant_name, find_browser, lang,
                    launch, log, open_with_system, run)

MUSIC_FILE = CACHE / "music.json"   # các bài bạn đã gọi, để Tom biết gu nhạc của bạn
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
YT_RESULT_RE = re.compile(
    r'"videoRenderer":\{"videoId":"([\w-]{11})".*?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"',
    re.S,
)

SPOTIFY_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-\w+/)?|spotify:)(track|album|playlist)[/:]([A-Za-z0-9]+)"
)
APP_NAME_RE = re.compile(r"\w[\w .+&'()-]{0,60}")
APP_DIRS = (Path("/Applications"), Path("/System/Applications"), Path.home() / "Applications")
WEEKDAYS_VI = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")
# Windows: lấy mọi app trong Start menu (cả app cài từ Microsoft Store) kèm mã để mở
START_APPS_PS = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                 "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress")
NOT_APPS_RE = re.compile(r"uninstall|gỡ cài đặt|read ?me|help|documentation", re.I)
# Tìm file: bỏ qua thư mục hệ thống, thư viện, cache (vừa chậm vừa toàn file không cần)
SKIP_DIRS = {".venv", "venv", "env", "node_modules", ".git", "__pycache__", "site-packages",
             "appdata", ".cache", "models", "$recycle.bin", ".conda", "anaconda3", "miniconda3"}
FILE_SEARCH_SECONDS = 4
_found: set[str] = set()   # file vừa tìm thấy: AI chỉ được mở các file này


def normalize(text: str) -> str:
    """Chữ thường, bỏ dấu, bỏ dấu câu: "Mở Zalo giúp tôi!" -> "mo zalo giup toi"."""
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def open_urls(urls: list[str], dry_run: bool = False) -> bool:
    """Mở link: trong tab duy nhất của trợ lý (SINGLE_TAB), hoặc cửa sổ trình duyệt mới."""
    urls = [u.strip() for u in urls if u.strip()]
    if not urls:
        return False
    if WINDOWS and cfg.SINGLE_TAB:
        if len(urls) > 1:
            log(f"ℹ️  Chỉ dùng một tab: mở {urls[-1]}, bỏ qua {len(urls) - 1} trang trước.")
        return browser.open_url(urls[-1], dry_run)
    name = cfg.BROWSER.strip()
    chromium = any(k in name.lower() for k in CHROMIUM_BROWSERS)
    if WINDOWS:
        exe = find_browser(name) if name else None
        if exe and (launch([exe, *(["--new-window"] if chromium else []), *urls], dry_run)
                    or dry_run):
            return True
        if name and not exe:
            log(f"⚠️  Không thấy trình duyệt “{name}”, dùng trình duyệt mặc định.")
        return all([open_with_system(u, dry_run) for u in urls])
    if chromium:
        # -n để Chrome đang chạy vẫn nhận được --new-window
        if run(["open", "-na", name, "--args", "--new-window", *urls], dry_run):
            return True
    elif name and run(["open", "-a", name, *urls], dry_run):
        return True
    return all([run(["open", u], dry_run) for u in urls])


@functools.cache
def _start_apps() -> dict[str, str]:
    """Windows: {tên app trong Start menu: mã để mở}."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", START_APPS_PS],
                           capture_output=True, timeout=20)
        items = json.loads(r.stdout.decode("utf-8", "ignore") or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        log(f"⚠️  Không đọc được danh sách ứng dụng: {e}")
        return {}
    if isinstance(items, dict):
        items = [items]
    return {i["Name"]: i["AppID"] for i in items
            if i.get("Name") and i.get("AppID") and not NOT_APPS_RE.search(i["Name"])}


def _open_windows_app(name: str, dry_run: bool) -> bool:
    apps = _start_apps()
    lower = {n.lower(): n for n in apps}
    # Đúng tên trước ("Zalo"), rồi tới tên bắt đầu bằng nó ("Telegram" -> "Telegram Desktop")
    match = lower.get(name.lower()) or next(
        (n for low, n in sorted(lower.items()) if low.startswith(name.lower())), None)
    if match:
        return open_with_system(f"shell:AppsFolder\\{apps[match]}", dry_run)
    return open_with_system(name, dry_run)   # app có đăng ký tên chạy, vd "notepad"


def open_app(name: str, dry_run: bool = False) -> bool:
    name = name.strip()
    if not APP_NAME_RE.fullmatch(name):   # chặn đường dẫn hay tham số lạ
        log(f"⚠️  Tên ứng dụng không hợp lệ: {name!r}")
        return False
    if WINDOWS:
        return _open_windows_app(name, dry_run)
    return run(["open", "-a", name], dry_run)


def open_target(target: str, dry_run: bool = False) -> bool:
    """Mục trong SHORTCUTS: địa chỉ web hoặc tên app."""
    if target.startswith(("http://", "https://")):
        return open_urls([target], dry_run)
    return open_app(target, dry_run)


def installed_apps() -> list[str]:
    if WINDOWS:
        return sorted(_start_apps())
    names = set()
    for folder in APP_DIRS:
        if folder.is_dir():
            names.update(p.stem for p in folder.glob("*.app"))
    return sorted(names)


def match_app(spoken: str) -> str | None:
    """Tên app đã cài khớp với câu nói ("excel" -> "Excel", "word" -> "Word"); None nếu không."""
    key = normalize(spoken)
    if len(key) < 3:
        return None
    apps = {normalize(n): n for n in installed_apps()}
    if key in apps:
        return apps[key]
    # "excel" khớp "Microsoft Excel"/"Excel 2016": tên app chứa nguyên cụm từ, chọn tên ngắn nhất
    hits = [n for k, n in apps.items() if re.search(rf"\b{re.escape(key)}\b", k)]
    return min(hits, key=len) if hits else None


# --- tìm file -----------------------------------------------------------------
def _search_roots() -> list[Path]:
    if cfg.FILE_SEARCH_DIRS:
        return [Path(os.path.expandvars(d)).expanduser() for d in cfg.FILE_SEARCH_DIRS]
    home = Path.home()
    roots = [home / d for d in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")]
    roots += [p for p in home.glob("OneDrive*") if p.is_dir()]
    return [r for r in roots if r.is_dir()]


def find_files(query: str, limit: int = 10) -> list[Path]:
    """File có tên chứa đủ các chữ trong câu (không dấu, không phân biệt hoa thường).

    Khớp nhiều chữ hơn và sửa gần đây hơn thì xếp trước. Tìm tối đa vài giây.
    """
    words = [w for w in normalize(query).split() if w not in {"file", "tep", "tai", "lieu", "cua", "toi"}]
    if not words:
        return []
    deadline = time.monotonic() + FILE_SEARCH_SECONDS
    hits: list[tuple[int, float, Path]] = []
    for root in _search_roots():
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                name = normalize(f)
                score = sum(w in name for w in words)
                if score == len(words) or (len(words) > 2 and score >= len(words) - 1):
                    p = Path(folder) / f
                    try:
                        hits.append((score, p.stat().st_mtime, p))
                    except OSError:
                        pass
            if time.monotonic() > deadline:
                log("ℹ️  Tìm file quá lâu, dừng ở kết quả hiện có.")
                break
        if time.monotonic() > deadline:
            break
    hits.sort(key=lambda h: (-h[0], -h[1]))
    found = [p for _, _, p in hits[:limit]]
    _found.update(str(p) for p in found)
    return found


def show_file(path: Path, dry_run: bool = False) -> bool:
    """Mở thư mục chứa file và chọn sẵn file đó (Windows Explorer / Finder)."""
    if WINDOWS:
        return bool(launch(["explorer", f"/select,{path}"], dry_run) or dry_run)
    return run(["open", "-R", str(path)], dry_run)


def open_file(path: str, dry_run: bool = False) -> bool:
    """Mở một file AI chọn, chỉ trong số file vừa tìm thấy (không cho mở đường dẫn lạ)."""
    if path not in _found:
        log(f"⚠️  Không mở file ngoài kết quả tìm kiếm: {path}")
        return False
    return open_with_system(path, dry_run) if WINDOWS else run(["open", path], dry_run)


def play_link(link: str, dry_run: bool = False) -> bool:
    """Phát một link YouTube/Spotify."""
    m = SPOTIFY_RE.search(link)
    if m and MAC and Path("/Applications/Spotify.app").exists():
        # Mở link thường chỉ hiện bài hát; lệnh này mới bắt Spotify phát luôn.
        uri = f"spotify:{m.group(1)}:{m.group(2)}"
        return run(["osascript", "-e", f'tell application "Spotify" to play track "{uri}"'],
                   dry_run)
    return open_urls([link], dry_run)


def play_song(dry_run: bool = False) -> bool:
    """Nhạc mở đầu của workflow: bài trong SONG, để trống thì chọn bài bạn hay nghe."""
    song = cfg.SONG.strip()
    return play_link(song, dry_run) if song else play_favorite(dry_run)


def youtube_search(query: str) -> tuple[str, str] | None:
    """Tìm trên YouTube, trả về (link, tên video) của kết quả đầu tiên. Không cần API key."""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA,
                                               "Accept-Language": "vi,en;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", "ignore")
    except OSError as e:
        log(f"⚠️  Không tìm được trên YouTube: {e}")
        return None
    m = YT_RESULT_RE.search(html)
    if not m:
        return None
    try:
        title = json.loads(f'"{m.group(2)}"')
    except ValueError:
        title = query
    return f"https://www.youtube.com/watch?v={m.group(1)}", title


def genre_of(query: str) -> str | None:
    """Thể loại nhạc trong câu ("nhạc remix sôi động" -> "remix"); None nếu là tên bài cụ thể."""
    key = f" {normalize(query)} "
    return next((g for g in cfg.MUSIC_GENRES if f" {normalize(g)} " in key), None)


def open_music_search(query: str, dry_run: bool = False) -> bool:
    """Mở trang YouTube tìm sẵn theo thể loại để người dùng tự chọn bài."""
    words = query.strip()
    if lang() == "vi" and not normalize(words).startswith("nhac"):
        words = "nhạc " + words
    elif lang() == "en" and "music" not in words.lower():
        words += " music"
    return open_urls(["https://www.youtube.com/results?search_query=" + urllib.parse.quote(words)],
                     dry_run)


def _load_music() -> dict:
    try:
        return json.loads(MUSIC_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def play_music(query: str, dry_run: bool = False) -> bool:
    """Phát bài theo tên bạn nói (tìm trên YouTube) và ghi nhớ để biết gu của bạn."""
    history = _load_music()
    key = query.lower().strip()
    entry = history.get(key)
    if entry is None:
        found = youtube_search(query)
        if found:
            log(f"🎵 Tìm thấy: {found[1]}")
            entry = {"url": found[0], "title": found[1], "count": 0}
        else:   # không lấy được kết quả: mở trang tìm kiếm để bạn tự chọn
            entry = {"url": "https://www.youtube.com/results?search_query="
                            + urllib.parse.quote(query), "title": query, "count": 0}
    entry["count"] += 1
    if not dry_run:
        history[key] = entry
        CACHE.mkdir(exist_ok=True)
        MUSIC_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
    return play_link(entry["url"], dry_run)


def play_favorite(dry_run: bool = False) -> bool:
    """Chọn ngẫu nhiên một bài bạn hay nghe; bài gọi càng nhiều càng dễ được chọn."""
    choices = [(e["url"], e.get("count", 1)) for e in _load_music().values()]
    choices += [(song, 2) for song in cfg.FAVORITE_SONGS if song.strip()]
    if not choices and cfg.SONG.strip():
        choices = [(cfg.SONG.strip(), 1)]
    if not choices:
        return False
    pick = random.choices([c[0] for c in choices], weights=[c[1] for c in choices])[0]
    if not pick.startswith(("http://", "https://", "spotify:")):
        found = youtube_search(pick)   # trong danh sách yêu thích có thể chỉ ghi tên bài
        if not found:
            return False
        pick = found[0]
    return play_link(pick, dry_run)


def fill(template: str, now: datetime | None = None, **extra: str) -> str:
    """Điền {greeting}, {time}, {date} (và các ô khác) vào một câu nói sẵn."""
    now = now or datetime.now()
    h = now.hour
    if lang() == "vi":
        greeting = ("Chào buổi sáng" if h < 11 else "Chào buổi trưa" if h < 13
                    else "Chào buổi chiều" if h < 18 else "Chào buổi tối")
        time_s = f"{h} giờ {now.minute} phút"
        date_s = f"{WEEKDAYS_VI[now.weekday()]}, ngày {now.day} tháng {now.month}"
    else:
        greeting = ("Good morning" if h < 12 else "Good afternoon" if h < 18
                    else "Good evening")
        # Không dùng "%-I", "%-d": Windows không hiểu, báo lỗi.
        time_s = f"{now.hour % 12 or 12}:{now:%M %p}"
        date_s = f"{now:%A, %B} {now.day}"
    try:
        return template.format(greeting=greeting, time=time_s, date=date_s,
                               me=assistant_name(), **extra).strip()
    except (KeyError, IndexError, ValueError):
        return template.strip()


def say(key: str, **extra: str) -> str:
    """Câu nói sẵn trong config.SAY theo tiếng đang dùng, đã điền giờ, ngày..."""
    phrases = cfg.SAY.get(lang()) or cfg.SAY["vi"]
    return fill(phrases[key], **extra)


def run_workflow(dry_run: bool = False) -> None:
    """Workflow kiểu trong video: mở nhạc, đọc lời chào, mở web và app."""
    log("🚀 Chạy workflow buổi sáng...")
    played = play_song(dry_run)

    def greet() -> None:
        if played and not dry_run:
            time.sleep(max(0.0, cfg.GREETING_DELAY_S))
        voice.speak(say("greeting"), dry_run=dry_run)

    # Nói ở luồng riêng để web và app mở ra ngay, không phải chờ nói xong.
    speaker = threading.Thread(target=greet)
    speaker.start()
    if dry_run:
        speaker.join()   # cho dòng in ra theo đúng thứ tự
    open_urls(cfg.URLS, dry_run)
    for app in cfg.APPS:
        open_app(app, dry_run)
    speaker.join()
