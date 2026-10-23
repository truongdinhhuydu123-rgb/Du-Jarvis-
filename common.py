"""Mấy hàm dùng chung cho mọi phần của trợ lý."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache"
LOG_FILE = CACHE / "tom.log"   # nhật ký lần chạy gần nhất, để xem lại khi có lỗi
MAC = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"

CHROMIUM_BROWSERS = ("chrome", "chromium", "brave", "edge")
# Windows: tên trình duyệt trong config -> tên file chạy của nó
BROWSER_EXES = {"chrome": "chrome.exe", "edge": "msedge.exe", "brave": "brave.exe",
                "firefox": "firefox.exe", "opera": "opera.exe"}

# Những thứ đổi theo từng câu khi đang chạy: tiếng để trả lời, tên người dùng vừa gọi.
NOW = {"lang": "", "name": ""}
VI_LETTERS = set("ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ")
# Gõ tiếng Việt không dấu ("mo youtube", "may gio roi") vẫn nhận ra nhờ mấy từ hay gặp.
VI_WORDS = {"oi", "mo", "bat", "nhac", "may", "gio", "roi", "hom", "nay", "toi", "cho", "giup",
            "tim", "gia", "vang", "la", "gi", "khong", "nhe", "ban", "minh", "thoi", "tiet", "tin",
            "moi", "nhat", "bao", "nhieu", "nao", "sao", "di", "lich", "tuan", "ngay"}
EN_WORDS = {"the", "is", "are", "what", "whats", "open", "play", "find", "how", "when", "where",
            "price", "news", "please", "me", "my", "to", "of", "and", "in", "for", "you", "can",
            "show", "search", "music", "time", "today", "it", "a", "some", "next", "latest", "hey"}


def lang() -> str:
    """Tiếng trợ lý đang trả lời: LANGUAGE trong config, hoặc theo câu vừa nói nếu "auto"."""
    import config as cfg

    if cfg.LANGUAGE in ("vi", "en"):
        return cfg.LANGUAGE
    return NOW["lang"] or "vi"


def assistant_name() -> str:
    """Tên trợ lý tự xưng: tên người dùng vừa gọi (Du hay Steve), mặc định tên đầu tiên."""
    import config as cfg

    return NOW["name"] or cfg.NAMES[0]


def detect_language(text: str) -> str | None:
    """'vi' hay 'en' theo chữ trong câu; None nếu không đoán được (giữ tiếng đang dùng)."""
    low = text.lower()
    if any(c in VI_LETTERS for c in low):
        return "vi"
    words = [w for w in "".join(c if c.isalnum() else " " for c in low).split() if w.isascii()]
    vi, en = sum(w in VI_WORDS for w in words), sum(w in EN_WORDS for w in words)
    return "vi" if vi > en else "en" if en > vi else None


def set_language(text: str) -> None:
    """LANGUAGE = "auto": trả lời bằng tiếng của câu người dùng vừa nói hoặc gõ."""
    import config as cfg

    if cfg.LANGUAGE == "auto":
        NOW["lang"] = detect_language(text) or NOW["lang"] or "vi"


def log(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run(cmd: list[str], dry_run: bool = False, env: dict | None = None) -> bool:
    """Chạy một lệnh hệ thống; lỗi thì chỉ cảnh báo chứ không làm trợ lý dừng."""
    if dry_run:
        print("   $", shlex.join(cmd))
        return True
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env)
    except OSError as e:
        log(f"⚠️  Không chạy được {cmd[0]}: {e}")
        return False
    if r.returncode != 0:
        log(f"⚠️  {shlex.join(cmd)} → {r.stderr.strip() or 'lỗi'}")
    return r.returncode == 0


def launch(cmd: list[str], dry_run: bool = False) -> subprocess.Popen | None:
    """Mở một chương trình rồi đi tiếp luôn, không chờ nó tắt (trình duyệt, app...)."""
    if dry_run:
        print("   $", shlex.join(cmd))
        return None
    try:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        log(f"⚠️  Không chạy được {cmd[0]}: {e}")
        return None


def open_with_system(target: str, dry_run: bool = False) -> bool:
    """Windows: mở link, file hay app bằng chương trình mặc định (như bấm đúp chuột)."""
    if dry_run:
        print("   $ start", target)
        return True
    try:
        os.startfile(target)
    except OSError as e:
        log(f"⚠️  Không mở được {target}: {e}")
        return False
    return True


def find_browser(name: str) -> str | None:
    """Windows: "Google Chrome" -> đường dẫn tới chrome.exe; không thấy thì None."""
    exe = next((e for key, e in BROWSER_EXES.items() if key in name.lower()), None)
    if not exe:
        return None
    import winreg

    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            path = winreg.QueryValue(
                root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}").strip('"')
        except OSError:
            continue
        if path and Path(path).is_file():
            return path
    return shutil.which(exe)


def groq_key() -> str:
    """Key Groq trong .env (nhận cả tên viết nhầm "Grok_API_KEY")."""
    return (os.environ.get("GROQ_API_KEY") or os.environ.get("GROK_API_KEY")
            or os.environ.get("Grok_API_KEY") or "").strip()


def load_env() -> None:
    """Đọc file .env (KEY=value) cạnh script; không ghi đè biến đã có sẵn."""
    env = HERE / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip("'\"")
            if value:
                os.environ.setdefault(key.strip(), value)
