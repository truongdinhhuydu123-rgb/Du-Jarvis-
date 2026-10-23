#!/usr/bin/env python3
"""Du / Steve: trợ lý giọng nói Việt-Anh cho Windows và macOS (phong cách JARVIS trong Iron Man).

Cách chạy:  Windows: gõ "run" (sau khi chạy "Tao lenh run.bat" một lần) hoặc bấm đúp "Start Tom.bat"
            Mac: bấm đúp "Start Tom.command"
Gọi:        "Du ơi, mấy giờ rồi?"   "Steve ơi, giá vàng thế nào?"   "Hey Steve, open YouTube"
Gõ:         gõ lệnh vào cửa sổ đen hoặc ô dưới HUD rồi Enter (không cần gọi tên)

Tuỳ chọn:
  --text        chỉ gõ phím, không dùng micro
  --ask "câu"   xử lý một câu rồi thoát
  --say "câu"   nghe thử giọng (bỏ trống = lời chào buổi sáng)
  --debug       hiện mức âm thanh của micro để chỉnh độ nhạy
  --hud         mở thử màn hình HUD (không cần micro)
  --telegram    chỉ chạy bot Telegram (bình thường bot tự chạy cùng trợ lý)
  --dry-run     chỉ in ra, không mở app/web và không phát tiếng

Mọi tuỳ chỉnh nằm trong config.py.
"""

from __future__ import annotations

import _thread
import argparse
import concurrent.futures
import contextlib
import difflib
import math
import random
import re
import sys
import threading
import time
import types
import warnings

warnings.filterwarnings("ignore", message=".*OpenSSL.*")   # cảnh báo vô hại của Python có sẵn trên Mac

if sys.platform == "win32":
    # In tiếng Việt và emoji ra cửa sổ dòng lệnh Windows không bị lỗi.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")

# Kiểm tra chứng chỉ HTTPS bằng kho chứng chỉ của máy, để vẫn chạy được khi phần mềm diệt
# virus (Avast, Kaspersky...) kiểm tra kết nối mạng.
with contextlib.suppress(ImportError):
    import truststore

    truststore.inject_into_ssl()

try:
    import config as cfg
except Exception as e:  # lỗi gõ sai trong config.py
    sys.exit(f"Lỗi trong config.py: {e}")

import actions
import hud as hud_module
import learn
import telegram_bot
import voice
from actions import normalize
from brain import Brain
from common import CACHE, LOG_FILE, NOW, assistant_name, lang, load_env, log, set_language

MUSIC_VERBS = {"bat", "mo", "phat", "nghe", "choi"}
MUSIC_NOUNS = {"nhac", "bai"}
TAIL_FILLERS = {"len", "di", "nhe", "giup", "toi", "cho", "voi", "nha", "minh", "coi", "xem", "nao"}
EN_MUSIC_TAIL = {"music", "songs", "song", "playlist", "please", "for", "me", "now", "on", "youtube"}
FILLERS = {"oi", "a", "au", "nay", "ne", "nhe", "da", "vang", "r", "e", "u", "ui", "hey", "ok", "okay"}
OPEN_RE = re.compile(r"^(?:hay |giup toi |please |can you |)(?:mo|bat|vao|chay|open|launch|start)"
                     r"(?: giup toi| cho toi| giup| the| up| me)? (.+?)"
                     r"(?: len| ra| giup toi| cho toi| di| nhe| voi| giup| please| for me| app)*$")
FIND_RE = re.compile(r"^(?:hay |giup toi |please |can you |)(?:tim kiem|tim|kiem|find|search for|"
                     r"search|look for|locate)(?: giup toi| cho toi| giup| me| my| the| a)* "
                     r"(?:file|tep|tai lieu|files|document|documents)(?: cua toi| ten la| ten| named"
                     r"| called)? (.+)$")
# Dạy trợ lý: "sửa chữ gia lô thành Zalo", "học chữ bực nhạc thành bật nhạc", "học: tiu => Steve",
# "learn tiu as Steve". Phải có "chữ/từ" hoặc dấu ":" để câu như "học tiếng Anh thành thạo..." không
# bị hiểu nhầm là lệnh dạy.
TEACH_RE = re.compile(r"^(?:(?:học|hoc|sửa|sua|dạy|day)\s+(?:chữ|chu|từ|tu)\b|(?:học|hoc)\s*:|learn\b|teach\b)"
                      r"\s*:?\s*[\"“'‘]?(.+?)[\"”'’]?(?:\s*(?:=>|->|=)\s*|\s+(?:thành|thanh|as|means)\s+)"
                      r"[\"“'‘]?(.+?)[\"”'’]?[.!?]*$", re.I)
FORGET_RE = re.compile(r"^(?:quên chữ|quen chu|quên từ|quen tu|forget)\s*:?\s*[\"“'‘]?(.+?)[\"”'’]?[.!?]*$",
                       re.I)
LEARNED_PHRASES = ("da hoc duoc gi", "hoc duoc gi", "hoc duoc nhung gi", "what have you learned",
                   "what did you learn")
TYPED_FIX_S = 40   # gõ lại câu đúng trong chừng này giây sau khi nói thì coi là sửa lỗi nghe
STOP = {normalize(w) for w in cfg.STOP_WORDS}
STOP_FILE = CACHE / "stop"   # lệnh "turn off" gõ trong PowerShell tạo file này


class Goodbye(Exception):
    pass


# "du ơi" -> "duoi": "Du";  "hey steve" -> "heysteve": "Steve"
WAKE = {normalize(w).replace(" ", ""): name for name, words in cfg.WAKE_WORDS.items() for w in words}
# "zalo|gia lô" -> {"zalo": ("zalo", "Zalo"), "gia lo": ("zalo", "Zalo")}: tên để đọc + đích
SHORTCUTS = {normalize(name): (names.split("|")[0].strip(), target)
             for names, target in cfg.SHORTCUTS.items() for name in names.split("|")}


def split_wake(text: str) -> str | None:
    """Tìm tên trợ lý ở đầu câu (có thể sau mấy tiếng đệm như "à", "ê", "này").

    Trả về phần lệnh phía sau ("" nếu chỉ gọi tên), None nếu câu không gọi trợ lý.
    Nhớ người dùng vừa gọi tên nào (Du hay Steve) để trợ lý tự xưng cho đúng.
    """
    words = text.split()
    keys = [normalize(w).replace(" ", "") for w in words]
    wake = {**learn.wake_variants(), **WAKE}   # cộng các cách gọi tên đã tự học
    skip = 0
    while skip < len(keys) and (not keys[skip] or keys[skip] in FILLERS):
        skip += 1
    # Thử cả từ đầu câu ("hey steve", "này du" có trong danh sách) lẫn sau tiếng đệm ("à du ơi").
    for start in dict.fromkeys((0, skip)):
        n = _wake_at(keys, start, wake)
        if not n:
            continue
        NOW["name"] = wake["".join(keys[start:start + n])]
        rest, rest_keys = words[start + n:], keys[start + n:]
        while rest:   # bỏ tiếng đệm và tên gọi lặp lại: "Steve ơi, Steve ơi, mở YouTube"
            if rest_keys[0] in FILLERS or not rest_keys[0]:
                rest, rest_keys = rest[1:], rest_keys[1:]
            elif (m := _wake_at(rest_keys, 0, wake)):
                rest, rest_keys = rest[m:], rest_keys[m:]
            else:
                break
        command = " ".join(rest).strip(" ,.!?…")
        return "" if len(normalize(command)) <= 2 else command
    return None


def wake_misheard(heard: str, wake_words: int, better: str) -> bool:
    """Bộ nghe nhanh nghe ra tên gọi ở `wake_words` chữ đầu của `heard`, bộ nghe kỹ thì không.

    True nếu bộ nghe kỹ chỉ viết tên khác đi ("Dua ơi", "Tiver ơi": vẫn là gọi trợ lý); False nếu
    nó nghe ra câu khác hẳn ("Tối nay ăn gì..." mà bộ nghe nhanh tưởng là "Du ơi, ...").
    """
    def start(text: str, n: int) -> str:
        return normalize(" ".join(text.split()[:n])).replace(" ", "")

    if difflib.SequenceMatcher(a=start(heard, wake_words), b=start(better, wake_words)).ratio() >= 0.7:
        return True
    keys = set(WAKE) | set(learn.wake_variants())
    for n in (1, 2, 3):
        head = start(better, n)
        if len(head) >= 4 and any(abs(len(head) - len(k)) <= 2
                                  and difflib.SequenceMatcher(a=head, b=k).ratio() >= 0.75 for k in keys):
            return True
    return False


def _wake_at(keys: list[str], start: int, wake: dict) -> int:
    """Số chữ của tên trợ lý bắt đầu ở vị trí start (0 nếu không có)."""
    for n in (3, 2, 1):   # "hey steve ơi", "du ơi" trước, rồi mới tới "steve"
        if start + n <= len(keys) and "".join(keys[start:start + n]) in wake:
            return n
    return 0


def parse_music(text: str) -> str | None:
    """ "bật nhạc Sơn Tùng" / "play Lạc Trôi" -> tên bài; "bật nhạc lên" -> ""; không phải nhạc -> None."""
    words = text.strip(" ,.!?").split()
    keys = [normalize(w) for w in words]
    if keys[:1] == ["play"] or keys[:2] == ["put", "on"]:   # tiếng Anh
        cut = 1 if keys[0] == "play" else 2
        words, keys = words[cut:], keys[cut:]
        while keys and keys[0] in {"me", "some", "the", "a", "my"}:
            words, keys = words[1:], keys[1:]
        while keys and (keys[-1] in EN_MUSIC_TAIL or not keys[-1]):
            words, keys = words[:-1], keys[:-1]
        return " ".join(words).strip(" ,.!?")
    start = 2 if keys[:2] in (["cho", "toi"], ["giup", "toi"]) else 0
    if len(keys) < start + 2 or keys[start] not in MUSIC_VERBS or keys[start + 1] not in MUSIC_NOUNS:
        return None
    words, keys = words[start + 2:], keys[start + 2:]
    while keys and keys[0] in {"hat", "cua", "ban"}:          # "bài hát", "nhạc của", "bản"
        words, keys = words[1:], keys[1:]
    while keys and (keys[-1] in TAIL_FILLERS or not keys[-1]):  # "... lên", "... giúp tôi"
        words, keys = words[:-1], keys[:-1]
    return " ".join(words).strip(" ,.!?")


def handle(text: str, brain: Brain, dry_run: bool = False) -> str | None:
    """Xử lý một câu lệnh, trả về câu trợ lý sẽ nói (None = đã tự nói rồi)."""
    norm = normalize(text)
    m = TEACH_RE.match(text.strip())
    if m:   # "học gia lô thành Zalo"
        wrong, right = m.group(1).strip(), m.group(2).strip()
        learn.teach(wrong, right)
        return actions.say("learned", name=wrong, n=right)
    m = FORGET_RE.match(text.strip())
    if m:
        return actions.say("forgot" if learn.forget(m.group(1)) else "not_learned", name=m.group(1))
    if any(p in norm for p in LEARNED_PHRASES):
        return learn.summary(lang())

    query = parse_music(text)
    if query is not None:
        genre = actions.genre_of(query) if query else None
        log(f"🎵 Nhạc: {query or '(bài bạn hay nghe)'}{' (thể loại)' if genre else ''}")
        if genre:   # "nhạc remix", "some lofi": mở trang YouTube tìm sẵn để chọn
            return actions.say("music_genre", name=query) if actions.open_music_search(query, dry_run) \
                else actions.say("open_failed", name="YouTube")
        if query:
            return actions.say("music_named", name=query) if actions.play_music(query, dry_run) \
                else actions.say("no_song")
        return actions.say("music" if actions.play_favorite(dry_run) else "no_song")

    if norm in STOP:   # "turn off" trơn (cả câu chỉ có vậy; "turn off the music" thì không)
        log("⚡ Lệnh nhanh: stop")
        raise Goodbye
    soft = " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())   # giữ dấu, bỏ dấu câu
    for action, phrases in cfg.COMMANDS.items():
        # Khớp nguyên từ ("tắt du" không khớp "tắt đường dây"), và câu phải gần như chỉ có lệnh,
        # để "cửa hàng mở lúc mấy giờ" vẫn đi hỏi AI. Lệnh tắt so cả dấu: "tắt Du" khác
        # "tắt dữ liệu".
        key, pick = (soft, str.lower) if action == "stop" else (norm, normalize)
        if any(f" {pick(p)} " in f" {key} " and len(key) - len(pick(p)) <= 15 for p in phrases):
            log(f"⚡ Lệnh nhanh: {action}")
            if action == "workflow":
                actions.run_workflow(dry_run)
                return None
            if action == "music":
                return actions.say("music" if actions.play_favorite(dry_run) else "no_song")
            if action == "time":
                return actions.say("time")
            if action == "date":
                return actions.say("date")
            if action == "stop":
                raise Goodbye

    m = FIND_RE.match(norm)
    if m:
        wanted = " ".join(text.strip(" ,.!?").split()[-len(m.group(1).split()):])
        log(f"🔍 Tìm file: {wanted}")
        found = actions.find_files(m.group(1))
        if not found:
            return actions.say("no_files", name=wanted)
        for p in found[:5]:
            log(f"   📄 {p}")
        actions.show_file(found[0], dry_run)
        return actions.say("found", n=str(len(found)), name=found[0].name)

    m = OPEN_RE.match(norm)
    if m and m.group(1) in SHORTCUTS:
        label, target = SHORTCUTS[m.group(1)]
        name = label if target.startswith("http") else target
        log(f"⚡ Mở: {target}")
        if actions.open_target(target, dry_run):
            return actions.say("opened", name=name)
        return actions.say("open_failed", name=name)
    app = actions.match_app(m.group(1)) if m else None
    if app:   # app bất kỳ trong Start menu: "mở excel", "open spotify"
        log(f"⚡ Mở app: {app}")
        return actions.say("opened" if actions.open_app(app, dry_run) else "open_failed", name=app)

    log("🧠 Hỏi AI...")
    started = time.monotonic()
    answer = brain.ask(text)
    log(f"🧠 Trả lời sau {time.monotonic() - started:.1f}s")
    return answer


def respond(text: str, brain: Brain, dry_run: bool) -> None:
    reply = handle(text, brain, dry_run)
    if reply:
        # Câu ngắn không có số (không phải giờ, ngày) thì lưu giọng lại, lần sau phát ngay.
        keep = len(reply) <= 60 and not any(c.isdigit() for c in reply)
        voice.speak(reply, keep=keep, dry_run=dry_run)


def respond_typed(text: str, brain: Brain, dry_run: bool) -> None:
    """Câu gõ (HUD, cửa sổ đen, --ask): không cần gọi tên; gọi tên trơn thì trả lời "có"."""
    command = split_wake(text)
    set_language(command or text)
    learn.note_words(command or text)
    if command == "":
        voice.speak(actions.say("yes"), keep=True, dry_run=dry_run)
    else:
        respond(command or text, brain, dry_run)


def research_notice(brain: Brain, hud, dry_run: bool):
    """Câu khó cần tra cứu: nói "chờ vài giây" song song với lúc tra, để bạn khỏi chờ trong im lặng."""
    def notice() -> None:
        hud.set(status="researching")

        def work() -> None:
            voice.speak(actions.say("researching"), keep=True, dry_run=dry_run)
            if brain.researching:   # đọc xong câu báo mà vẫn đang tra: HUD hiện lại "đang nghiên cứu"
                hud.set(status="researching")
        threading.Thread(target=work, daemon=True).start()
    return notice


def make_brain(dry_run: bool, hud=None) -> Brain:
    brain = Brain(dry_run)
    brain.on_research = research_notice(brain, hud or hud_module.NoHud(), dry_run)
    return brain


def common_phrases() -> list[str]:
    """Các câu hay nói, để tạo sẵn giọng lúc khởi động."""
    phrases = [actions.say(k) for k in ("yes", "music", "bye", "searched", "no_song", "researching")]
    phrases.append(actions.say("music_named", name=""))
    for label, target in SHORTCUTS.values():
        phrases.append(actions.say("opened", name=label if target.startswith("http") else target))
    return list(dict.fromkeys(phrases))


def says_stop(text: str, ears, audio) -> bool:
    """Câu chỉ có "turn off" (không cần gọi tên). Nghe gần giống thì nhờ Groq nghe lại cho chắc."""
    import difflib

    norm = normalize(text)
    if norm in STOP:
        return True
    if not norm or len(norm.split()) > 3:
        return False
    letters = norm.replace(" ", "")
    if max(difflib.SequenceMatcher(a=letters, b=s.replace(" ", "")).ratio() for s in STOP) < 0.6:
        return False
    better = ears.refine(audio, text)
    return normalize(better) in STOP


def watch_stop_file(on_stop) -> None:
    """Gõ  turn off  trong PowerShell/cửa sổ lệnh: lệnh đó tạo file .cache/stop, thấy là tắt."""
    STOP_FILE.unlink(missing_ok=True)   # file sót lại từ lần trước (lúc trợ lý không chạy)

    def loop() -> None:
        while not STOP_FILE.exists():
            time.sleep(0.5)
        STOP_FILE.unlink(missing_ok=True)
        on_stop()
    threading.Thread(target=loop, daemon=True).start()


def read_keyboard(handler) -> None:
    """Gõ lệnh ngay trong cửa sổ đen rồi Enter, song song với nghe micro."""
    def loop() -> None:
        while True:
            try:
                line = input()
            except (EOFError, OSError, ValueError):
                return
            if line.strip():
                handler(line.strip())
    threading.Thread(target=loop, daemon=True).start()


def assistant(debug: bool, dry_run: bool) -> None:
    from listen import Microphone, Transcriber

    LOG_FILE.parent.mkdir(exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")

    ears = Transcriber()
    mic = Microphone()
    brain = Brain(dry_run)
    busy = threading.Lock()   # giọng nói, nút bấm HUD và chữ gõ không chạy chồng lên nhau
    last_voice = {"text": "", "at": 0.0}   # lệnh nói gần nhất, để học khi bạn gõ lại câu đúng
    learned = learn.counts()
    log(f"🎓 Tự học: đã nhớ {learned['fixes']} chữ hay nghe nhầm, {learned['wake']} cách gọi tên, "
        f"{learned['words']} từ quen.")

    def on_text(text: str) -> None:
        with busy, mic.paused():
            hud.set(status="thinking", heard=text)
            # Vừa nói xong mà gõ lại câu gần giống: chỗ khác nhau là chỗ máy nghe nhầm -> học.
            if last_voice["text"] and time.monotonic() - last_voice["at"] < TYPED_FIX_S:
                learn.observe_pair(last_voice["text"], split_wake(text) or text, "typed")
                last_voice["text"] = ""
            try:
                respond_typed(text, brain, dry_run)
            except Goodbye:
                voice.speak(actions.say("bye"), keep=True, dry_run=dry_run)
                _thread.interrupt_main()   # dừng vòng nghe chính
            hud.set(status="idle")

    hud = hud_module.start(mic, on_text, open_window=not dry_run)
    brain.on_research = research_notice(brain, hud, dry_run)
    voice.listeners.append(_show_speech(hud))
    voice.prune_cache()
    with mic.paused():
        voice.speak(actions.say("ready"), keep=True, dry_run=dry_run)
    if not dry_run:
        voice.warm_up(common_phrases())
    names = " / ".join(cfg.NAMES)
    log(f'Nói "{cfg.NAMES[0]} ơi, ..." hoặc "Hey {cfg.NAMES[-1]}, ..." để ra lệnh ({names}).')
    log("⌨  Hoặc gõ lệnh vào đây (hay ô dưới HUD) rồi Enter, không cần gọi tên. "
        "Tắt: nói hoặc gõ “turn off”.")
    read_keyboard(on_text)
    telegram_bot.start(dry_run)   # nhắn Telegram từ điện thoại (nếu có TELEGRAM_BOT_TOKEN)

    def on_stop() -> None:
        log("⏻ Nhận lệnh turn off từ cửa sổ lệnh.")
        with busy, mic.paused():
            voice.speak(actions.say("bye"), keep=True, dry_run=dry_run)
        _thread.interrupt_main()   # dừng vòng nghe chính, đóng HUD như khi Ctrl+C

    watch_stop_file(on_stop)

    awake_until = 0.0   # trong khoảng này nói tiếp không cần gọi tên
    early = concurrent.futures.ThreadPoolExecutor(max_workers=1)   # nhận dạng sẵn khi bạn vừa ngừng
    ignored = learn.RecentIgnored()   # câu vừa bị bỏ qua (chỉ trong RAM), để học cách gọi tên

    def not_addressed(heard: str) -> None:
        ignored.add(heard)
        # Không gọi trợ lý: không ghi chuyện riêng vào nhật ký (trừ khi SHOW_IGNORED/--debug);
        # chỉ hiện tạm trên HUD vài giây để bạn thấy máy nghe ra gì khi gọi mà không được.
        log(f"👂 {heard}   (chưa gọi {names}, bỏ qua)" if cfg.SHOW_IGNORED or debug
            else f"👂 (không gọi {names}, bỏ qua)")
        hud.set(note=f"Nghe được: “{heard}”. Hãy bắt đầu bằng “{cfg.NAMES[0]} ơi…” "
                     f"hoặc “Hey {cfg.NAMES[-1]}…”", note_at=time.time())

    while True:
        guesses: list[concurrent.futures.Future] = []

        def on_pause(snippet) -> None:
            """Bạn vừa ngừng nói: nhận dạng luôn, khỏi đợi hết khoảng im lặng cuối câu."""
            for old in guesses:
                old.cancel()   # bạn nói tiếp sau lần ngừng trước: bỏ bản cũ nếu chưa chạy
            guesses.append(early.submit(ears.transcribe, snippet))

        awake = time.monotonic() < awake_until
        hud.set(status="awake" if awake else "idle")
        audio = mic.listen(timeout=max(awake_until - time.monotonic(), 0.1) if awake else None,
                           meter=debug, on_pause=None if ears.engine == "groq" else on_pause)
        if audio is None:
            awake_until = 0.0
            log("💤 Chờ gọi tên...")
            continue
        # Micro vẫn nghe tiếp trong lúc nhận dạng, để câu nói ngay sau không bị mất chữ.
        hud.set(status="thinking")
        if debug:
            save_wav(CACHE / "last_utterance.wav", audio)   # để xem lại khi nghe sai
        started = time.monotonic()
        text = guesses[-1].result() if guesses and mic.pause_valid else ears.transcribe(audio)
        if not text:
            log(f"👂 (có tiếng {len(audio) / 16000:.1f}s nhưng không nghe ra chữ)")
            continue
        command = split_wake(text)
        if command is None and not awake and says_stop(text, ears, audio):
            log(f"👂 {text}   (turn off)")
            raise Goodbye   # main() nói lời chào rồi tắt
        if command is None and not awake:
            not_addressed(text)
            continue
        # Câu gọi trợ lý (kể cả chỉ gọi tên) hay nói tiếp sau khi vừa trả lời: nghe kỹ lại bằng
        # Groq / bộ nghe kỹ. Bộ nghe nhanh hay nghe nhầm tiếng ồn, câu nói chuyện xung quanh
        # thành tên gọi; bộ nghe kỹ quyết định cuối.
        better = ears.refine(audio, text)
        if not better:
            log("👂 (nghe kỹ lại thì không có lời nói, bỏ qua)")
            continue
        if better != text:
            redo = split_wake(better)
            if redo is not None or awake:
                command = redo
            else:
                skip = len(text.split()) - len(command.split())   # số chữ của tên gọi
                if not wake_misheard(text, skip, better):   # "Tối nay ăn gì" chứ không phải "Du ơi..."
                    not_addressed(better)
                    continue
                # Groq viết tên khác đi ("Tiver ơi"): giữ cách hiểu tên của máy, lấy lệnh của Groq
                command = " ".join(better.split()[skip:]).strip(" ,.!?…")
            text = better
        heard_in = time.monotonic() - started
        set_language(command or text)
        log(f"👂 {text}   (nhận dạng {heard_in:.1f}s, trả lời bằng {'tiếng Việt' if lang() == 'vi' else 'tiếng Anh'})")
        # Tự học: độ to giọng bạn, từ bạn hay dùng, cách gọi tên vừa bị nghe nhầm ngay trước đó.
        learn.remember_level(mic.last_speech_level)
        learn.note_words(command or "")
        ignored.learn_from(command or "", NOW["name"] or cfg.NAMES[0], set(WAKE) | set(learn.wake_variants()))
        last_voice.update(text=command or "", at=time.monotonic())
        with busy, mic.paused():
            hud.set(heard=text)
            if command == "":
                voice.speak(actions.say("yes"), keep=True, dry_run=dry_run)
            else:
                voice.chime()
                respond(command or text, brain, dry_run)
        awake_until = time.monotonic() + cfg.FOLLOW_UP_S


def save_wav(path, audio) -> None:
    import wave

    import numpy as np

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())


def _show_speech(hud):
    """Khi trợ lý bắt đầu nói: HUD chuyển sang trạng thái "đang nói" và hiện câu trả lời."""
    def listener(event: str, text: str) -> None:
        if event == "start":
            hud.set(status="speaking", reply=text)
    return listener


def hud_demo(dry_run: bool) -> None:
    """Mở thử HUD không cần micro: tự đổi trạng thái để xem hiệu ứng; bấm nút, gõ lệnh vẫn chạy."""
    fake_mic = types.SimpleNamespace(level=0.0, hearing=False)
    brain = Brain(dry_run)

    def on_text(text: str) -> None:
        hud.set(status="thinking", heard=text)
        with contextlib.suppress(Goodbye):
            respond_typed(text, brain, dry_run)
        hud.set(status="idle")

    hud = hud_module.start(fake_mic, on_text, open_window=not dry_run)
    if isinstance(hud, hud_module.NoHud):
        log("HUD đang tắt (HUD = False trong config.py).")
        return
    brain.on_research = research_notice(brain, hud, dry_run)
    voice.listeners.append(_show_speech(hud))
    log("Đang chạy thử HUD. Bấm Ctrl+C để thoát.")
    scenes = [
        ("idle", 4, {}),
        ("awake", 4, {"heard": f"{cfg.NAMES[0]} ơi, giá vàng hôm nay thế nào?"}),
        ("thinking", 3, {}),
        ("speaking", 5, {"reply": "Gold is trading near 4,146 dollars, down a third of a percent today."
                         if lang() == "en" else
                         "Vàng đang quanh 4.146 đô, giảm 0,3 phần trăm trong ngày."}),
    ]
    while True:
        for status, seconds, extra in scenes:
            hud.set(status=status, **extra)
            fake_mic.hearing = status == "awake"
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                fake_mic.level = 0.015 + 0.05 * random.random() * abs(math.sin(time.time() * 6)) if fake_mic.hearing else 0.0
                time.sleep(0.05)
        fake_mic.hearing = False


def typing(dry_run: bool) -> None:
    brain = make_brain(dry_run)
    print("Gõ câu lệnh rồi Enter. Ctrl+C để thoát.")
    while True:
        try:
            line = input("\nBạn: ").strip()
        except EOFError:
            return
        if line:
            respond_typed(line, brain, dry_run)


def main() -> int:
    ap = argparse.ArgumentParser(description=f"{assistant_name()}: trợ lý giọng nói Việt-Anh.")
    ap.add_argument("--text", action="store_true", help="chỉ gõ phím, không dùng micro")
    ap.add_argument("--ask", metavar="CÂU", help="xử lý một câu rồi thoát")
    ap.add_argument("--say", nargs="?", const="", metavar="CÂU",
                    help="nghe thử giọng (bỏ trống = lời chào)")
    ap.add_argument("--debug", action="store_true", help="hiện mức âm thanh của micro")
    ap.add_argument("--hud", action="store_true", help="mở thử màn hình HUD (không cần micro)")
    ap.add_argument("--telegram", action="store_true",
                    help="chỉ chạy bot Telegram (không micro, không HUD)")
    ap.add_argument("--dry-run", action="store_true",
                    help="chỉ in ra, không mở app/web và không phát tiếng")
    args = ap.parse_args()
    load_env()

    try:
        if args.say is not None:
            set_language(args.say)
            voice.speak(args.say or actions.say("greeting"), dry_run=args.dry_run)
        elif args.ask:
            respond_typed(args.ask, make_brain(args.dry_run), args.dry_run)
        elif args.text:
            typing(args.dry_run)
        elif args.hud:
            hud_demo(args.dry_run)
        elif args.telegram:
            return telegram_bot.run_only(args.dry_run)
        else:
            assistant(args.debug, args.dry_run)
    except Goodbye:
        voice.speak(actions.say("bye"), keep=True, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print()
        log("Đã dừng.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
