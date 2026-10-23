"""Tự học: trợ lý nghe hiểu bạn tốt dần lên theo thời gian dùng, lưu trong .cache/hoc.json.

Học từ 5 nguồn, không cần huấn luyện lại mô hình (máy không có GPU):
  1. Thầy dạy trò: câu gọi trợ lý được Whisper bản lớn (Groq) nghe lại; chỗ bộ nghe nhanh trên
     máy nghe khác Groq, lặp lại từ 3 lần trở lên, thành bảng "nghe X thì hiểu là Y" để máy tự
     sửa (nhận tên gọi đúng hơn, và nghe đúng hơn cả khi mất mạng).
  2. Bạn sửa: vừa nói xong mà gõ lại câu đúng (trong 40 giây) thì học ngay chỗ khác nhau.
  3. Bạn dạy: "học gia lô thành Zalo", "sửa chữ bực nhạc thành bật nhạc", "quên chữ gia lô".
  4. Cách gọi tên: gọi mà trợ lý không nhận ("Tiu ơi, mở YouTube"), rồi gọi lại đúng ngay sau
     đó với cùng lệnh, thì "tiu ơi" được học thành một cách gọi tên.
  5. Thói quen: từ riêng bạn hay nói (XAUUSD, TradingView, tên người...) được đưa cho Whisper
     "nghe trước"; độ to giọng bạn hay nói dùng để chỉnh độ nhạy micro.
"""

from __future__ import annotations

import collections
import difflib
import json
import re
import statistics
import threading
import time

import config as cfg
from common import CACHE, log

FILE = CACHE / "hoc.json"
PROMOTE_AFTER = 3        # cặp nghe nhầm do Groq chỉ ra, gặp đủ chừng này lần thì học (chắc là lỗi
                         #   lặp lại của máy, không phải tình cờ)
MIN_SIMILAR = 0.5        # hai câu giống nhau ít nhất chừng này mới coi là "cùng một câu, nghe khác"
SOUND_ALIKE = 0.3        # chữ sai và chữ đúng phải na ná nhau (tránh học nhầm khi bạn đổi ý)
MAX_WORDS = 60           # nhớ tối đa chừng này từ quen
PUNCT = " ,.!?…;:\"'“”()[]"
# Chữ thường gặp: đổi qua lại giữa mấy chữ này thường là đổi ý, không phải nghe nhầm.
COMMON = set("""toi ban minh no ho la thi ma va voi cho cua o tai trong ngoai len xuong ra vao
di den nay kia do roi chua khong co duoc bi se da dang mot hai ba bon nam sau bay tam chin muoi
gi sao nao bao nhieu may hom qua mai nay a oi nhe nha ha u da vang uh um
the a an is are was to of in on at for and or but it this that you i me my we he she they
what how when where why which who can do does""".split())

_lock = threading.Lock()
_data: dict | None = None


def _normalize(text: str) -> str:
    from actions import normalize   # tránh import vòng lúc khởi động
    return normalize(text)


def _load() -> dict:
    global _data
    if _data is None:
        try:
            _data = json.loads(FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _data = {}
        # fixes: bạn dạy/gõ lại, sửa mọi chữ.  local_fixes: học từ Groq, chỉ sửa chữ máy nghe
        # (không bao giờ đè lên chữ Groq nghe, vì Groq là "thầy").
        for key, empty in (("fixes", {}), ("local_fixes", {}), ("candidates", {}), ("words", {}),
                           ("wake", {}), ("levels", []), ("stats", {})):
            _data.setdefault(key, empty)
    return _data


def _save() -> None:
    try:
        CACHE.mkdir(exist_ok=True)
        FILE.write_text(json.dumps(_data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log(f"⚠️  Không lưu được bộ nhớ tự học: {e}")


def _count(stat: str) -> None:
    _data["stats"][stat] = _data["stats"].get(stat, 0) + 1


# --- sửa chữ nghe nhầm ---------------------------------------------------------
def fixes(local: bool = True) -> dict[str, str]:
    """Bảng "nghe X -> hiểu Y": SUA_CHU trong config + những gì đã tự học.

    local=False (chữ Groq nghe): bỏ phần học từ Groq, chỉ dùng SUA_CHU và chữ bạn dạy.
    """
    with _lock:
        data = _load()
        learned = {**(data["local_fixes"] if local else {}), **data["fixes"]} if cfg.LEARN else {}
    return {**{k.lower(): v for k, v in cfg.SUA_CHU.items()}, **learned}


def apply_fixes(text: str, local: bool = True) -> str:
    """Sửa các chữ hay nghe nhầm (cụm dài sửa trước)."""
    table = fixes(local)
    for wrong in sorted(table, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(wrong)}(?!\w)", table[wrong], text, flags=re.IGNORECASE)
    return text


def teach(wrong: str, right: str, source: str = "bạn dạy", local_only: bool = False) -> bool:
    wrong, right = wrong.strip(PUNCT).lower(), right.strip(PUNCT)
    if not wrong or not right or _normalize(wrong) == _normalize(right):
        return False
    with _lock:
        data = _load()
        table = data["local_fixes" if local_only else "fixes"]
        if table.get(wrong) == right:
            return False
        table[wrong] = right
        data["candidates"].pop(f"{wrong}\t{right}", None)
        _count("fixes_learned")
        _save()
    log(f"🎓 Đã học ({source}): nghe “{wrong}” thì hiểu là “{right}”.")
    return True


def forget(wrong: str) -> bool:
    key = _normalize(wrong.strip(PUNCT))
    with _lock:
        data = _load()
        hits = []
        for table in (data["fixes"], data["local_fixes"]):
            found = [k for k in table if _normalize(k) == key]   # mọi cách viết dấu của chữ đó
            for k in found:
                del table[k]
            hits += found
        if hits:
            _save()
    if hits:
        log(f"🎓 Đã quên: {', '.join(f'“{k}”' for k in hits)}.")
    return bool(hits)


def _letters(text: str) -> str:
    """Chữ không dấu, bỏ khoảng trắng: "tra đinh viu" -> "tradinhviu" (so như nghe, không theo từ)."""
    return _normalize(text).replace(" ", "")


def _pairs(heard: str, right: str, sound_check: bool = True) -> list[tuple[str, str]]:
    """Các chỗ nghe nhầm giữa hai cách nghe cùng một câu: [("gia lô", "Zalo"), ...].

    So theo chữ cái chứ không theo từ, vì máy hay nghe một từ tiếng Anh thành vài âm tiết
    tiếng Việt ("TradingView" -> "tra đinh viu").
    """
    if difflib.SequenceMatcher(a=_letters(heard), b=_letters(right)).ratio() < MIN_SIMILAR:
        return []   # hai câu khác hẳn: bạn nói câu khác chứ không phải sửa lỗi nghe
    a, b = heard.split(), right.split()
    matcher = difflib.SequenceMatcher(a=[_normalize(w) for w in a], b=[_normalize(w) for w in b],
                                      autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or i2 - i1 > 4 or j2 - j1 > 3:
            continue
        wrong, fix = " ".join(a[i1:i2]).strip(PUNCT), " ".join(b[j1:j2]).strip(PUNCT)
        nw, nf = _normalize(wrong), _normalize(fix)
        if not nw or not nf or nw == nf or any(c.isdigit() for c in nw + nf):
            continue   # chỉ khác dấu/hoa thường, hoặc là số ("mười" / "10")
        if set(nw.split()) <= COMMON and set(nf.split()) <= COMMON:
            continue   # đổi giữa mấy chữ thường gặp: có lẽ đổi ý ("hôm nay" -> "hôm qua")
        if sound_check and difflib.SequenceMatcher(a=_letters(wrong), b=_letters(fix)).ratio() < SOUND_ALIKE:
            continue   # không giống âm: có lẽ hai bên hiểu khác nhau chứ không phải nghe nhầm
        out.append((wrong.lower(), fix))
    return out


def observe_pair(heard: str, right: str, source: str) -> None:
    """Hai cách nghe cùng một câu: "typed" (bạn gõ lại) học ngay; "groq" chờ lặp lại đủ lần."""
    if not cfg.LEARN or not heard or not right:
        return
    for wrong, fix in _pairs(heard, right, sound_check=source != "typed"):
        if source == "typed":
            teach(wrong, fix, "bạn gõ lại câu đúng")
            continue
        key = f"{wrong}\t{fix}"
        with _lock:
            data = _load()
            if data["fixes"].get(wrong) == fix or data["local_fixes"].get(wrong) == fix:
                continue
            seen = data["candidates"][key] = data["candidates"].get(key, 0) + 1
            if len(data["candidates"]) > 300:   # bỏ bớt cặp chỉ gặp một lần, cũ nhất trước
                for k in [k for k, n in data["candidates"].items() if n < 2][:100]:
                    del data["candidates"][k]
            _save()
        if seen >= PROMOTE_AFTER:
            teach(wrong, fix, f"Groq nghe lại {seen} lần", local_only=True)


# --- cách gọi tên ---------------------------------------------------------------
def wake_variants() -> dict[str, str]:
    """Cách gọi tên đã học: {"tiuoi": "Steve"} (chữ không dấu, bỏ khoảng trắng)."""
    with _lock:
        return dict(_load()["wake"]) if cfg.LEARN else {}


def learn_wake(words: list[str], name: str) -> None:
    key = "".join(_normalize(w).replace(" ", "") for w in words)
    if not key or len(key) < 3 or all(_normalize(w) in COMMON for w in words):
        return
    with _lock:
        data = _load()
        if data["wake"].get(key) == name:
            return
        data["wake"][key] = name
        _count("wake_learned")
        _save()
    log(f"🎓 Đã học cách gọi tên mới: “{' '.join(words)}” = {name}.")


# --- từ quen và độ to giọng ---------------------------------------------------------
def note_words(text: str) -> None:
    """Ghi nhận từ riêng bạn hay nói: chữ viết hoa giữa câu, mã (XAUUSD, US100), từ tiếng Anh."""
    if not cfg.LEARN:
        return
    tokens = re.findall(r"[^\W_][\w&+.-]*", text)
    vietnamese = any(c in "ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
                     for c in text.lower())
    picked = []
    for i, tok in enumerate(tokens):
        if len(tok) < 2 or _normalize(tok) in COMMON:
            continue
        has_caps = any(c.isupper() for c in tok[1:]) or (tok.isupper() and len(tok) >= 2)
        proper = i > 0 and tok[0].isupper()
        english = vietnamese and tok.isascii() and tok.isalpha() and len(tok) >= 4
        if has_caps or proper or any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok) or english:
            picked.append(tok.strip("."))
    if not picked:
        return
    with _lock:
        words = _load()["words"]
        for w in picked:
            words[w] = words.get(w, 0) + 1
        if len(words) > MAX_WORDS * 2:   # bỏ bớt từ ít dùng
            for w, _ in sorted(words.items(), key=lambda kv: kv[1])[:len(words) - MAX_WORDS]:
                del words[w]
        _save()


def vocab(limit: int = 15) -> list[str]:
    """Từ quen đã gặp từ 2 lần trở lên, hay dùng nhất trước."""
    with _lock:
        words = _load()["words"] if cfg.LEARN else {}
        return [w for w, n in sorted(words.items(), key=lambda kv: -kv[1]) if n >= 2][:limit]


def remember_level(level: float) -> None:
    """Độ to giọng của câu bạn vừa gọi trợ lý (nhớ 30 câu gần nhất)."""
    if not cfg.LEARN or level <= 0:
        return
    with _lock:
        levels = _load()["levels"]
        levels.append(round(level, 5))
        del levels[:-30]
        _save()


def typical_level() -> float:
    """Độ to giọng thường ngày của bạn (0 nếu chưa đủ dữ liệu)."""
    with _lock:
        levels = _load()["levels"] if cfg.LEARN else []
        return statistics.median(levels) if len(levels) >= 5 else 0.0


# --- báo cáo ------------------------------------------------------------------------
def summary(lang: str) -> str:
    with _lock:
        data = _load()
        fixes_, wake = {**data["local_fixes"], **data["fixes"]}, data["wake"]
        words = [w for w, n in data["words"].items() if n >= 2]
    examples = ", ".join(f"{k} thành {v}" if lang == "vi" else f"{k} as {v}"
                         for k, v in list(fixes_.items())[-3:])
    if lang == "en":
        text = (f"So far I've learned {len(fixes_)} corrections, {len(wake)} new ways to call my name, "
                f"and {len(words)} words you often use.")
        return text + (f" Latest: {examples}." if examples else "")
    text = (f"Tôi đã học {len(fixes_)} chữ hay nghe nhầm, {len(wake)} cách gọi tên mới "
            f"và {len(words)} từ bạn hay dùng.")
    return text + (f" Gần đây: {examples}." if examples else "")


def counts() -> dict:
    with _lock:
        data = _load()
        return {"fixes": len(data["fixes"]) + len(data["local_fixes"]), "wake": len(data["wake"]),
                "words": sum(1 for n in data["words"].values() if n >= 2)}


class RecentIgnored:
    """Nhớ tạm (trong RAM, không ghi ra đĩa) vài câu vừa bị bỏ qua, để học cách gọi tên."""

    def __init__(self, seconds: float = 20.0) -> None:
        self.seconds = seconds
        self.items: collections.deque = collections.deque(maxlen=5)

    def add(self, text: str) -> None:
        self.items.append((time.monotonic(), text))

    def learn_from(self, command: str, name: str, wake_keys: set[str]) -> None:
        """Lệnh vừa nhận giống phần cuối một câu vừa bị bỏ qua: phần đầu câu đó là cách gọi tên."""
        if not cfg.LEARN or not command:
            return
        target = [_normalize(w) for w in command.split()]
        now = time.monotonic()
        for when, text in list(self.items):
            if now - when > self.seconds:
                continue
            words = text.split()
            if len(words) <= len(target):
                continue
            tail = [_normalize(w) for w in words[-len(target):]]
            if difflib.SequenceMatcher(a=tail, b=target).ratio() < 0.75:
                continue
            prefix = words[:len(words) - len(target)]
            if 1 <= len(prefix) <= 3:
                key = "".join(_normalize(w).replace(" ", "") for w in prefix)
                if key not in wake_keys:
                    learn_wake([w.strip(PUNCT) for w in prefix], name)
            self.items.clear()
            return
