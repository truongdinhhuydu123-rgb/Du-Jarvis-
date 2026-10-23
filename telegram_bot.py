"""Bot Telegram: hỏi trợ lý từ điện thoại, nhận bản tin, ghi chú lên Google Calendar.

Chỉ chat của bạn (TELEGRAM_CHAT_ID trong .env) dùng được bot. Người lạ nhắn thì bot chỉ trả lời
chat ID của họ, không hỏi AI, không ghi lịch (không tốn lượt AI của bạn).

  /capnhat, "cập nhật", "bản tin"     bản tin thị trường, vàng SJC, lãi suất, luật, tin hot
  /note ..., "ghi chú ...", "nhắc tôi ..."   lên Google Calendar
  câu khác                             hỏi AI (câu khó tự tra cứu nhiều nguồn)

Chạy ngầm mỗi khi bật máy: "Chay ngam Telegram.bat" (gỡ: "Tat chay ngam Telegram.bat"). Tin nhắn
gửi lúc máy tắt được xử lý khi máy bật lại; mỗi sáng tự gửi bản tin (BAN_TIN_TU_DONG trong config).
Mỗi lúc chỉ một bot chạy: đang chạy ngầm thì cửa sổ trợ lý (run) không chạy thêm bot nữa.

Nói chuyện với Telegram bằng HTTPS thường (getUpdates/sendMessage), không cần thư viện thêm.
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import config as cfg
from actions import normalize
from brain import Brain
from common import CACHE, log, set_language

API = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 4000   # Telegram cho tối đa 4096 ký tự một tin
LATE_S = 120      # tin cũ hơn chừng này (gửi lúc máy tắt) thì trả lời kèm giờ gửi
STATE_FILE = CACHE / "telegram.json"   # bản tin tự động đã gửi những lần nào
BRIEF_WORDS = {"capnhat", "update", "bantin", "news"}
BRIEF_PHRASES = ("cap nhat", "ban tin", "tin hom nay", "tin moi hom nay", "co gi moi", "update",
                 "daily news", "news today", "briefing")
# "lịch tin tuần này" là câu hỏi, không phải ghi chú: chỉ lệnh /lich mới là ghi lịch.
NOTE_RE = re.compile(r"^\s*(?:/(?:note|ghichu|lich)(?:@\w+)?|ghi ch[uú]|note|"
                     r"nh[aắ]c (?:t[oô]i|m[iì]nh|em|anh)|remind me(?: to)?)\b\s*[:\-–]?\s*(.*)$",
                     re.I | re.S)
HELP = """\
Du / Steve đây. Bạn có thể:
• /capnhat hoặc "cập nhật": bản tin thị trường, giá vàng SJC, lãi suất, luật kinh doanh, tin hot
• /note mai 9h họp anh Nam (hoặc "ghi chú ...", "nhắc tôi ..."): đưa lên Google Calendar
• Hỏi bất cứ gì, vd "giá vàng SJC hôm nay", "phân tích XAUUSD tuần này"
Câu khó tôi sẽ tra nhiều nguồn rồi mới trả lời (mất khoảng 10 giây)."""
_lock_socket: socket.socket | None = None


def _owners() -> set[int]:
    ids = set()
    for part in re.split(r"[,\s]+", os.environ.get("TELEGRAM_CHAT_ID", "")):
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return ids


def claim() -> bool:
    """Giữ quyền chạy bot trên máy này (một cổng nội bộ). False = bot đang chạy ở chỗ khác.

    Telegram chỉ cho một nơi nhận tin của bot; hai nơi cùng nhận thì cả hai báo lỗi liên tục.
    """
    global _lock_socket
    if _lock_socket is not None:
        return True
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):   # Windows: không cho chương trình khác dùng chung cổng
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        s.bind(("127.0.0.1", cfg.TELEGRAM_LOCK_PORT))
    except OSError:
        s.close()
        return False
    _lock_socket = s
    return True


class TelegramBot:
    def __init__(self, token: str, dry_run: bool = False) -> None:
        self.token = token
        self.owners = _owners()
        self.brain = Brain(dry_run, channel="chat")
        self._offset = 0

    # --- gọi Telegram -------------------------------------------------------------
    def _call(self, method: str, http_timeout: float = 20, **params) -> dict:
        req = urllib.request.Request(API.format(token=self.token, method=method),
                                     data=json.dumps(params).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=http_timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:   # Telegram trả lỗi kèm mô tả trong JSON
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            raise TelegramError(e.code, body.get("description") or str(e)) from None

    def send(self, chat_id: int, text: str) -> None:
        text = text.strip() or "…"
        while text:
            part, text = text[:MAX_TEXT], text[MAX_TEXT:]
            if text:   # cắt ở chỗ xuống dòng gần nhất cho dễ đọc
                cut = part.rfind("\n")
                if cut > MAX_TEXT // 2:
                    part, text = part[:cut], part[cut + 1:] + text
            self._call("sendMessage", chat_id=chat_id, text=part, disable_web_page_preview=True)

    def _typing(self, chat_id: int, stop: threading.Event) -> None:
        """Hiện "đang nhập..." trên điện thoại trong lúc trợ lý nghĩ (Telegram tắt sau 5 giây)."""
        while not stop.is_set():
            try:
                self._call("sendChatAction", http_timeout=10, chat_id=chat_id, action="typing")
            except Exception:
                pass
            stop.wait(4.5)

    # --- vòng nhận tin --------------------------------------------------------------
    def run_forever(self) -> None:
        try:
            me = self._call("getMe")["result"]
        except Exception as e:
            log(f"⚠️  Telegram: token không dùng được ({e}). Kiểm tra TELEGRAM_BOT_TOKEN trong .env.")
            return
        if self._on_google():
            return
        who = ", ".join(map(str, sorted(self.owners))) or "chưa đặt TELEGRAM_CHAT_ID"
        log(f"📱 Telegram: bot @{me.get('username')} đang chạy (chủ: {who}).")
        failures = 0
        while True:
            self._scheduled_briefing()
            try:
                # Chờ tin mới tối đa 30 giây mỗi lần hỏi (long polling): không tốn mạng khi im.
                updates = self._call("getUpdates", http_timeout=40, offset=self._offset, timeout=30,
                                     allowed_updates=["message"])["result"]
                failures = 0
            except TelegramError as e:
                if e.code == 409 and self._on_google():
                    return
                if e.code == 409:   # bot đang chạy ở một máy khác
                    log("⚠️  Telegram: bot đang chạy ở chỗ khác; thử lại sau 60 giây.")
                    time.sleep(60)
                else:
                    log(f"⚠️  Telegram lỗi ({e}); thử lại sau 15 giây.")
                    time.sleep(15)
                continue
            except Exception as e:   # mất mạng, máy vừa ngủ dậy...
                failures += 1
                if failures in (1, 10):
                    log(f"⚠️  Telegram: mất kết nối ({str(e)[:80]}); tự thử lại.")
                time.sleep(min(5 * failures, 60))
                continue
            messages = []
            for update in updates:
                self._offset = update["update_id"] + 1
                message = update.get("message") or {}
                if message.get("text"):
                    messages.append(message)
            for message in self._skip_repeated_briefings(messages):
                try:
                    self.handle(message)
                except Exception as e:
                    log(f"⚠️  Telegram: xử lý tin nhắn lỗi: {e}")

    def _on_google(self) -> bool:
        """Bot đã chạy trên máy chủ Google (google-cloud/bot-telegram.gs, Telegram gửi tin thẳng
        tới đó): máy tính không nhận tin nữa, để hai nơi không tranh nhau."""
        try:
            url = self._call("getWebhookInfo")["result"].get("url")
        except Exception:
            return False
        if url:
            log("📱 Telegram: bot đang chạy trên máy chủ Google; máy tính không cần chạy bot.")
        return bool(url)

    def _skip_repeated_briefings(self, messages: list[dict]) -> list[dict]:
        """Máy vừa bật lên mà có nhiều lần "cập nhật" đang chờ: chỉ làm một bản tin (lần cuối)."""
        briefs = [m for m in messages if _is_briefing(m["text"])]
        return [m for m in messages if not _is_briefing(m["text"]) or m is briefs[-1]]

    def handle(self, message: dict) -> None:
        chat = message["chat"]["id"]
        text = message["text"].strip()
        sender = message.get("from") or {}
        if chat not in self.owners:
            name = " ".join(filter(None, (sender.get("first_name"), sender.get("last_name"))))
            log(f"📱 Telegram: {name or 'người lạ'} (chat {chat}) nhắn bot; không phải chủ, bỏ qua.")
            hint = ("\nThêm TELEGRAM_CHAT_ID=" + str(chat) + " vào file .env trên máy rồi bật lại trợ lý."
                    if not self.owners else "")
            self.send(chat, f"Đây là trợ lý riêng. Chat ID của bạn: {chat}{hint}")
            return
        sent_at = datetime.fromtimestamp(message.get("date", time.time()))
        age = (datetime.now() - sent_at).total_seconds()
        if age > cfg.TELEGRAM_LATE_HOURS * 3600:
            log(f"📱 Telegram: bỏ qua tin quá cũ ({sent_at:%H:%M %d/%m}): {text[:40]}")
            return
        late = age > LATE_S
        log(f"📱 Telegram{f' (tin lúc {sent_at:%H:%M %d/%m})' if late else ''}: {text}")
        if text.split()[0].split("@")[0].lower() in ("/start", "/help", "/trogiup"):
            self.send(chat, HELP)
            return

        stop = threading.Event()
        threading.Thread(target=self._typing, args=(chat, stop), daemon=True).start()
        self.brain.on_research = lambda: self.send(chat, "🔎 Câu này cần tra cứu kỹ, chờ tôi vài giây…")
        started = time.monotonic()
        try:
            set_language(text)
            reply = self._reply(text, sent_at)
        finally:
            stop.set()
        log(f"📱 Telegram: trả lời sau {time.monotonic() - started:.1f}s")
        if late and not _is_briefing(text):
            reply = f"⏰ Trả lời tin lúc {sent_at:%H:%M %d/%m} (lúc đó máy tính đang tắt):\n{reply}"
        self.send(chat, reply)

    def _reply(self, text: str, sent_at: datetime) -> str:
        if _is_briefing(text):
            log("📱 Telegram: bản tin cập nhật")
            return self.brain.briefing()
        note = NOTE_RE.match(text)
        if note and note.group(1).strip():
            # "tối nay", "mai" tính theo lúc bạn nhắn, không phải lúc máy bật lên xử lý.
            return self.brain.ask(
                f"Tin nhắn này gửi lúc {sent_at:%H:%M %A %d/%m/%Y}; hiểu \"hôm nay\", \"tối nay\", \"mai\" "
                "theo thời điểm đó. Đưa ghi chú sau lên Google Calendar bằng công cụ add_calendar_event "
                "(có ngày giờ thì đặt đúng ngày giờ đó; không có thì để cả ngày, đúng ngày đó), rồi báo "
                f"lại ngắn gọn đã lưu gì, lúc nào: {note.group(1).strip()}", deep=False)
        if text.startswith("/"):
            return HELP
        return self.brain.ask(text)

    # --- bản tin tự động -----------------------------------------------------------
    def _scheduled_briefing(self) -> None:
        """Gửi bản tin vào các giờ trong BAN_TIN_TU_DONG (máy bật muộn thì gửi bù trong 3 giờ)."""
        if not (cfg.BAN_TIN_TU_DONG and self.owners):
            return
        now = datetime.now()
        state = _load_state()
        for hhmm in cfg.BAN_TIN_TU_DONG:
            try:
                hour, minute = (int(x) for x in hhmm.split(":"))
            except ValueError:
                continue
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            key = f"{due:%Y-%m-%d} {hhmm}"
            if not (due <= now < due + timedelta(hours=3)) or key in state["sent"]:
                continue
            state["sent"] = (state["sent"] + [key])[-30:]
            _save_state(state)   # lưu trước: bản tin lỗi giữa chừng thì cũng không gửi lặp mãi
            log(f"📱 Telegram: gửi bản tin tự động {hhmm}")
            try:
                text = self.brain.briefing()
                for chat in self.owners:
                    self.send(chat, text)
            except Exception as e:
                log(f"⚠️  Telegram: bản tin tự động lỗi: {e}")


def _is_briefing(text: str) -> bool:
    norm = normalize(text)
    words = norm.split()
    return bool(words) and ((text.startswith("/") and words[0] in BRIEF_WORDS)
                            or (len(words) <= 6 and any(p in norm for p in BRIEF_PHRASES)))


def _load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state.setdefault("sent", [])
    return state


def _save_state(state: dict) -> None:
    CACHE.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


class TelegramError(Exception):
    def __init__(self, code: int, description: str) -> None:
        super().__init__(f"HTTP {code}: {description}")
        self.code = code


def _token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def start(dry_run: bool = False) -> TelegramBot | None:
    """Bật bot ở luồng nền nếu có token (TELEGRAM = True), trừ khi bot đang chạy ngầm sẵn."""
    if not (cfg.TELEGRAM and _token()):
        return None
    if not claim():
        log("📱 Telegram: bot đang chạy ngầm sẵn, cửa sổ này không chạy thêm.")
        return None
    bot = TelegramBot(_token(), dry_run)
    threading.Thread(target=bot.run_forever, daemon=True).start()
    return bot


def run_only(dry_run: bool = False) -> int:
    """Chỉ chạy bot (jarvis.py --telegram, dùng khi chạy ngầm)."""
    if not _token():
        log("Chưa có TELEGRAM_BOT_TOKEN trong .env.")
        return 1
    if not claim():
        log("📱 Telegram: bot đã đang chạy (ngầm hoặc trong cửa sổ trợ lý); không chạy thêm.")
        return 0
    log("Chỉ chạy bot Telegram. Bấm Ctrl+C để dừng.")
    TelegramBot(_token(), dry_run).run_forever()
    return 0
