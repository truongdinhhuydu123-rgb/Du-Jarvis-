"""Tai của trợ lý: micro -> tách từng câu nói -> Whisper chuyển thành chữ -> sửa chữ nghe nhầm.

Hai bước nghe:
  1. Nghe tên gọi: bộ nghe rất nhỏ trên máy (WAKE_MODEL, ~0,5 giây/câu) nghe MỌI câu để biết có
     ai gọi trợ lý không. Câu không gọi trợ lý không rời khỏi máy, và máy không phải gồng.
  2. Nghe kỹ câu lệnh (chỉ câu gọi trợ lý), theo LISTEN_ENGINE trong config:
       "lai"  Whisper large-v3 của Groq (chuẩn nhất, ~1 giây, gửi dạng Opus ~8 KB); Groq lỗi hay
              chậm thì bộ nghe kỹ trên máy (WHISPER_MODEL) nghe thay.
       "may"  bộ nghe kỹ trên máy, không cần mạng.
       "groq" mọi câu (cả bước 1) gửi Groq: nhẹ máy nhất, nhưng mọi câu nói xung quanh lên mạng.
Bộ nghe được "nghe trước" câu mẫu + từ riêng (TU_RIENG, TU_TIENG_ANH, từ quen đã học) để viết đúng
tên, mã, chữ tiếng Anh; sau đó sửa chữ hay nghe nhầm (SUA_CHU + chữ đã tự học, xem learn.py).
"""

from __future__ import annotations

import collections
import contextlib
import http.client
import io
import json
import math
import queue
import ssl
import threading
import time
import urllib.error
import uuid

import numpy as np
import sounddevice as sd

import config as cfg
import learn
from common import HERE, MAC, groq_key, log

WHISPER_RATE = 16000
TURBO_REPO = "mlx-community/whisper-large-v3-turbo"
TURBO_DIR = HERE / "models" / "whisper-large-v3-turbo-mlx"
GROQ_HOST = "api.groq.com"
GROQ_PATH = "/openai/v1/audio/transcriptions"
# Groq lỗi thì nghe trên máy một lúc rồi thử lại: key sai lâu, quá giới hạn vừa; mạng chập chờn
# thì chỉ nghỉ khi lỗi liền GROQ_FAILS_BEFORE_PAUSE lần (một lần lỗi lẻ chỉ bỏ qua câu đó).
GROQ_PAUSE_S = {401: 600, 403: 600, 429: 60}
GROQ_PAUSE_OTHER_S = 30
GROQ_FAILS_BEFORE_PAUSE = 2
PROMPT_TOKENS = 200      # Whisper chỉ đọc ~224 token câu mẫu; chừa chỗ cho an toàn
MAX_WAKE_TOKENS = 80     # bộ nghe nhanh viết tối đa chừng này token (~40 chữ, đủ một câu lệnh)
BLOCK_S = 0.03
PRE_ROLL_S = 0.5         # giữ lại chút âm thanh ngay trước lúc bắt đầu nói (để không mất chữ đầu)
START_S = 0.09           # to liên tục chừng này mới tính là bắt đầu nói
END_SILENCE_S = 1.0      # im chừng này thì coi như nói xong câu (ngừng lấy hơi không bị cắt)
LONG_SPEECH_S = 3.0      # đã nói dài hơn chừng này (câu hỏi dài, hay ngừng nghĩ) thì
LONG_END_SILENCE_S = 1.4 #   chờ im lâu hơn chút mới chốt câu, đỡ bị cắt ngang
EARLY_S = 0.35           # vừa im chừng này đã đưa đi nhận dạng sẵn, trong lúc chờ đủ END_SILENCE_S
MIN_UTTERANCE_S = 0.4
MAX_UTTERANCE_S = 20.0
FLOOR_ALPHA = 0.995      # nền ồn bám theo phòng chậm cỡ nào (gần 1 = chậm)
MAX_FLOOR = 0.005        # lúc đo ban đầu, nền ồn tối đa chừng này (lỡ đo lúc có nhạc vẫn nghe được)

MIC_BLOCKED = ("Micro không có tiếng (chưa được cấp quyền?). Vào System Settings → Privacy & "
               "Security → Microphone, bật cho Terminal rồi chạy lại trợ lý." if MAC else
               "Micro không có tiếng (chưa được cấp quyền?). Vào Settings → Privacy & security → "
               "Microphone, bật “Let desktop apps access your microphone” rồi chạy lại trợ lý.")

# Whisper hay "bịa" mấy câu này khi nghe tiếng ồn không có lời.
HALLUCINATIONS = ("subscribe", "đăng ký kênh", "ghiền mì gõ", "like và share",
                  "hẹn gặp lại các bạn", "cảm ơn các bạn đã theo dõi", "cảm ơn các bạn đã xem",
                  "thanks for watching", "thank you for watching")


class Transcriber:
    """Chuyển âm thanh thành chữ (xem đầu file).

    transcribe(): bước 1, nghe nhanh mọi câu.   refine(): bước 2, nghe kỹ câu gọi trợ lý.
    """

    def __init__(self) -> None:
        self._wake = self._full = self._mlx = None
        self._lock = threading.Lock()   # nhận dạng sẵn chạy ở luồng khác: mỗi lúc chỉ một câu
        self._groq_key = groq_key()
        self._groq_pause_until = 0.0
        self._groq_fails = 0
        self._loading_full = False
        self.engine = cfg.LISTEN_ENGINE if cfg.LISTEN_ENGINE in ("lai", "may", "groq") else "lai"
        self.raw = ""            # chữ bước 1 nghe được, trước khi sửa (cho tự học)
        self.source = ""         # chữ cuối cùng do ai nghe: "máy nhanh", "Groq", "máy kỹ"
        if self.engine != "may" and not self._groq_key:
            log("⚠️  Chưa có GROQ_API_KEY trong .env: chỉ nghe trên máy.")
            self.engine = "may"
        if self.engine == "groq":
            log(f"Bộ nghe: Groq ({cfg.GROQ_MODEL}) cho mọi câu; máy chỉ nghe khi Groq lỗi.")
            return
        self._wake = self._load("wake", cfg.WAKE_MODEL)
        if self.engine == "may":
            self._load_full()
        log("Bộ nghe: " + (f"máy ({cfg.WAKE_MODEL}) nhận tên gọi, Groq ({cfg.GROQ_MODEL}) nghe kỹ lệnh."
                           if self.engine == "lai" else
                           f"máy ({cfg.WAKE_MODEL}) nhận tên gọi, máy ({cfg.WHISPER_MODEL}) nghe kỹ lệnh."))
        if self._groq_key:
            threading.Thread(target=_GROQ.warm_up, daemon=True).start()   # bắt tay sẵn với Groq

    # --- bộ nghe trên máy ---------------------------------------------------------
    def _load(self, role: str, name: str):
        from faster_whisper import WhisperModel

        log(f"Đang nạp bộ nghe {name} ({'nhận tên gọi' if role == 'wake' else 'nghe kỹ'})...")
        model = WhisperModel(name, device="cpu", compute_type="int8", download_root=str(HERE / "models"))
        model.transcribe(np.zeros(WHISPER_RATE, np.float32), language=cfg.LISTEN_LANGUAGE)   # chạy mồi
        return model

    def _load_full(self) -> None:
        """Bộ nghe kỹ trên máy: turbo bằng GPU chip Apple, hoặc WHISPER_MODEL bằng CPU."""
        if self._mlx is not None or self._full is not None:
            return
        if cfg.WHISPER_MODEL == "turbo" and MAC:
            try:
                import mlx_whisper

                if not (TURBO_DIR / "weights.safetensors").is_file():
                    from huggingface_hub import snapshot_download

                    log("Đang tải bộ nghe turbo (1.5 GB, chỉ tải lần đầu)...")
                    snapshot_download(TURBO_REPO, local_dir=str(TURBO_DIR))
                self._mlx = mlx_whisper
                return
            except Exception as e:   # máy không có chip Apple, thiếu thư viện, lỗi tải...
                log(f"⚠️  Không chạy được bộ nghe turbo ({e}); dùng bản nhỏ.")
        name = "large-v3-turbo" if cfg.WHISPER_MODEL == "turbo" and not MAC else cfg.WHISPER_MODEL
        self._full = self._load("full", "small" if name == "turbo" else name)

    def _run_local(self, model, audio: np.ndarray, prompt: str, beam: int) -> str:
        if model == "mlx":
            result = self._mlx.transcribe(audio, path_or_hf_repo=str(TURBO_DIR),
                                          language=cfg.LISTEN_LANGUAGE, temperature=0.0,
                                          condition_on_previous_text=False,
                                          initial_prompt=prompt or None, verbose=None)
            return " ".join(s["text"].strip() for s in result["segments"]
                            if s.get("no_speech_prob", 0) < 0.6)
        segments, _ = model.transcribe(
            audio, language=cfg.LISTEN_LANGUAGE, beam_size=beam,
            vad_filter=True,                 # bỏ đoạn không có tiếng người
            condition_on_previous_text=False, initial_prompt=prompt or None,
            without_timestamps=True,
            # Gặp tiếng ồn, Whisper hay "bịa" câu dài rồi tự thử lại nhiều lần (có lần mất 9 giây).
            # Bộ nghe nhanh chỉ thử một lần và chỉ viết đủ một câu lệnh; bộ nghe kỹ thử tối đa 3 lần.
            temperature=0.0 if beam == 1 else (0.0, 0.2, 0.4),
            max_new_tokens=MAX_WAKE_TOKENS if beam == 1 else None,
        )
        return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6)

    def _count_tokens(self, text: str) -> int:
        model = self._full or self._wake
        if model is not None:
            return len(model.hf_tokenizer.encode(" " + text).ids)
        return len(text) // 3 + 1   # ước lượng khi không có bộ nghe trên máy

    # --- Groq -------------------------------------------------------------------------
    def groq_ready(self) -> bool:
        return bool(self._groq_key) and time.monotonic() >= self._groq_pause_until

    def _groq(self, audio: np.ndarray, prompt: str) -> str:
        try:
            text = groq_transcribe(_opus_bytes(audio), "cau.ogg", prompt, self._groq_key,
                                   cfg.GROQ_TIMEOUT_S)
            self._groq_fails = 0
            return text
        except urllib.error.HTTPError as e:
            pause = GROQ_PAUSE_S.get(e.code, GROQ_PAUSE_OTHER_S)
            log(f"⚠️  Groq nghe lỗi (HTTP {e.code}); nghe trên máy {pause} giây.")
            self._groq_pause_until = time.monotonic() + pause
            raise
        except (OSError, ValueError, KeyError, http.client.HTTPException) as e:   # mạng, quá giờ...
            self._groq_fails += 1
            if self._groq_fails >= GROQ_FAILS_BEFORE_PAUSE:
                log(f"⚠️  Groq lỗi {self._groq_fails} lần liền ({e}); nghe trên máy {GROQ_PAUSE_OTHER_S} giây.")
                self._groq_pause_until = time.monotonic() + GROQ_PAUSE_OTHER_S
                self._groq_fails = 0
            else:
                log(f"⚠️  Groq nghe lỗi ({e}); câu này nghe trên máy.")
            raise

    # --- dùng từ ngoài --------------------------------------------------------------
    def transcribe(self, audio: np.ndarray) -> str:
        """Bước 1: nghe nhanh mọi câu để biết có gọi trợ lý không (chữ đã sửa nghe nhầm)."""
        with self._lock:
            if self.engine == "groq" and self.groq_ready():
                with contextlib.suppress(Exception):
                    self.raw = self._groq(audio, full_prompt(self._count_tokens)).strip()
                    self.source = "Groq"
                    return _clean(self.raw, full_prompt(self._count_tokens), local=False)
            if self._wake is None:   # chế độ "groq" mà Groq lỗi
                self._wake = self._load("wake", cfg.WAKE_MODEL)
            prompt = wake_prompt()
            self.raw = self._run_local(self._wake, audio, prompt, beam=1).strip()
            self.source = "máy nhanh"
            return _clean(self.raw, prompt, local=True)

    def refine(self, audio: np.ndarray, text: str) -> str:
        """Bước 2: câu gọi trợ lý được nghe kỹ lại (Groq, hoặc bộ nghe kỹ trên máy).

        Groq là người quyết định cuối: Groq nghe ra "" (chỉ có tiếng ồn) thì trả về "", vì bộ
        nghe nhanh hay nghe tiếng ồn thành "Du ơi, mấy giờ rồi" (câu giống câu mẫu của nó).
        Chỗ Groq nghe khác bộ nghe nhanh được bộ tự học ghi nhận: lặp lại đủ lần thì bộ nghe
        nhanh tự sửa, nhận tên gọi và lệnh đúng hơn (kể cả khi mất mạng).
        """
        if self.source == "Groq":
            return text
        raw = self.raw
        started = time.monotonic()
        better, by = None, ""
        if self.engine == "lai" and self.groq_ready():
            with contextlib.suppress(Exception):
                prompt = full_prompt(self._count_tokens)
                heard = self._groq(audio, prompt).strip()
                if _echoes_prompt(heard, prompt):   # nghe không rõ nên đọc lại câu mẫu: nghe lại trơn
                    heard = self._groq(audio, "").strip()
                better = _clean(heard, prompt, local=False)
                by = "Groq"
                if heard and not better:
                    log("👂 Groq nghe kỹ: chỉ có tiếng ồn (Whisper bịa câu quen thuộc), bỏ qua.")
                    self.source = by
                    return ""
                if better:
                    learn.observe_pair(raw, better, "groq")
        if better is None and self._mlx is None and self._full is None and self.engine == "lai":
            # Bộ nghe kỹ trên máy chưa nạp (nạp mất vài giây): dùng luôn chữ bộ nghe nhanh, nạp
            # bộ nghe kỹ ở luồng nền để lần sau Groq lỗi thì có sẵn.
            self._load_full_background()
            return text
        if better is None:
            with self._lock:
                self._load_full()
                prompt = full_prompt(self._count_tokens)
                better = _clean(self._run_local("mlx" if self._mlx else self._full, audio, prompt, beam=5),
                                prompt, local=True)
                by = "máy kỹ"
        log(f"👂 {by} nghe kỹ ({time.monotonic() - started:.1f}s): {better or '(không có lời)'}")
        self.source = by
        return better if by == "Groq" else better or text

    def _load_full_background(self) -> None:
        if self._loading_full:
            return
        self._loading_full = True

        # Không giữ khoá: bước nghe tên gọi vẫn chạy bình thường trong lúc nạp.
        threading.Thread(target=self._load_full, daemon=True).start()


def _clean(text: str, prompt: str, local: bool) -> str:
    """Sửa chữ nghe nhầm; bỏ chữ Whisper "bịa" khi chỉ có tiếng ồn."""
    text = learn.apply_fixes(text.strip(), local=local)
    if (any(h in text.lower() for h in HALLUCINATIONS) or _gibberish(text)
            or _echoes_prompt(text, prompt)):
        return ""
    return text


class _GroqSession:
    """Giữ một kết nối HTTPS tới Groq, khỏi bắt tay (TLS) lại mỗi câu: nhanh hơn, ít lỗi quá giờ."""

    def __init__(self) -> None:
        self._conn: http.client.HTTPSConnection | None = None
        self._lock = threading.Lock()

    def _close(self) -> None:
        with contextlib.suppress(Exception):
            if self._conn:
                self._conn.close()
        self._conn = None

    def warm_up(self) -> None:
        with contextlib.suppress(Exception), self._lock:
            if self._conn is None:
                self._conn = http.client.HTTPSConnection(GROQ_HOST, timeout=10,
                                                         context=ssl.create_default_context())
                self._conn.connect()

    def post(self, body: bytes, headers: dict, timeout: float) -> tuple[int, bytes]:
        with self._lock:
            for attempt in range(2):
                fresh = self._conn is None
                try:
                    if fresh:
                        self._conn = http.client.HTTPSConnection(GROQ_HOST, timeout=timeout,
                                                                 context=ssl.create_default_context())
                    self._conn.timeout = timeout
                    if self._conn.sock:
                        self._conn.sock.settimeout(timeout)
                    self._conn.request("POST", GROQ_PATH, body=body, headers=headers)
                    resp = self._conn.getresponse()
                    return resp.status, resp.read()
                except (http.client.RemoteDisconnected, http.client.CannotSendRequest,
                        http.client.ResponseNotReady, BrokenPipeError, ConnectionResetError):
                    # Kết nối cũ đã bị Groq đóng (để lâu không dùng): nối lại một lần.
                    self._close()
                    if fresh or attempt:
                        raise
                except Exception:
                    self._close()
                    raise
        raise OSError("không gửi được tới Groq")


_GROQ = _GroqSession()


def groq_transcribe(data: bytes, filename: str, prompt: str = "", key: str = "",
                    timeout: float = 20) -> str:
    """Gửi một file âm thanh (ogg, wav, mp3...) cho Whisper của Groq, trả về chữ (chưa sửa)."""
    key = key or groq_key()
    if not key:
        raise ValueError("chưa có GROQ_API_KEY")
    boundary = uuid.uuid4().hex
    fields = {"model": cfg.GROQ_MODEL, "language": cfg.LISTEN_LANGUAGE, "temperature": "0",
              "response_format": "json", "prompt": prompt}
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                    .encode() for k, v in fields.items() if v)
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             f"Content-Type: application/octet-stream\r\n\r\n").encode() + data
    body += f"\r\n--{boundary}--\r\n".encode()
    status, payload = _GROQ.post(body, {
        "Authorization": f"Bearer {key}", "User-Agent": "DuSteve/1.0",
        "Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout)
    if status != 200:
        raise urllib.error.HTTPError(f"https://{GROQ_HOST}{GROQ_PATH}", status,
                                     payload[:200].decode("utf-8", "ignore"), None, None)
    return json.loads(payload)["text"].strip()


def wake_prompt() -> str:
    """Câu mẫu ngắn cho bộ nghe nhanh: chỉ cách gọi tên + vài lệnh (đã thử: nhận tên đúng 14/14)."""
    first, second = cfg.NAMES[0], cfg.NAMES[-1]
    return (f"{first} ơi, mấy giờ rồi. {second} ơi, mở YouTube. Này {first}, bật nhạc. "
            f"Hey {second}, what time is it? Hey {first}, play some music.")


def full_prompt(count_tokens=lambda t: len(t) // 3 + 1) -> str:
    """Câu mẫu + từ riêng cho bước nghe kỹ, gói gọn trong ~200 token.

    Câu mẫu tiếng Việt chen tiếng Anh: Whisper bắt chước cách viết của câu mẫu, nên giữ nguyên
    chữ tiếng Anh, mã giao dịch thay vì phiên âm ("check", "update" chứ không ra "chéc", "ấp đết").
    Sau đó là tên trợ lý, TU_RIENG, từ quen tự học và TU_TIENG_ANH, nhiều nhất có thể cho vừa.
    """
    first, second = cfg.NAMES[0], cfg.NAMES[-1]
    example = (f"{first} ơi, check giá XAUUSD với Nasdaq, mở TradingView, xem tin CPI và FOMC "
               f"rồi update file Excel giúp tôi. Hey {second}, what's the gold price?")
    words, seen = [], set()
    for w in [*cfg.NAMES, *cfg.TU_RIENG, *learn.vocab(), *cfg.TU_TIENG_ANH]:
        if w and w.lower() not in seen:
            seen.add(w.lower())
            words.append(w)
    for i in range(len(words), 0, -1):   # bớt dần từ cuối danh sách cho vừa giới hạn
        candidate = f"{example} {', '.join(words[:i])}."
        if count_tokens(candidate) <= PROMPT_TOKENS:
            return candidate
    return example


# Tên cũ, để phone.py hay code khác gọi vẫn chạy.
vocabulary_prompt = full_prompt


def _echoes_prompt(text: str, prompt: str) -> bool:
    """Gặp tiếng ồn, Whisper đôi khi đọc lại nguyên câu mẫu/danh sách từ thay vì nghe.

    Chỉ xét câu dài (từ 8 chữ): câu ngắn trùng câu mẫu ("Hey Steve, what time is it?") là lệnh thật.
    """
    from actions import normalize

    words = normalize(text).split()
    return len(words) >= 8 and " ".join(words) in normalize(prompt)


def _opus_bytes(audio: np.ndarray) -> bytes:
    """Nén giọng nói sang Opus (~8 KB/câu thay vì ~100 KB WAV): gửi Groq nhanh hơn nhiều."""
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, np.clip(audio, -1, 1), WHISPER_RATE, format="OGG", subtype="OPUS")
    return buf.getvalue()


class Microphone:
    """Nghe micro liên tục và cắt ra từng câu nói dựa trên độ to."""

    def __init__(self) -> None:
        self.device = cfg.INPUT_DEVICE
        try:
            dev = sd.query_devices(self.device, "input")
        except (ValueError, sd.PortAudioError):
            if self.device is None:
                raise SystemExit("Không tìm thấy micro nào.")
            log(f"⚠️  Không thấy micro “{self.device}”, dùng micro mặc định.")
            self.device = None
            dev = sd.query_devices(None, "input")
        self.rate = WHISPER_RATE
        try:
            sd.check_input_settings(device=self.device, samplerate=self.rate, channels=1)
        except sd.PortAudioError:
            self.rate = int(dev["default_samplerate"])   # sẽ đổi về 16 kHz sau khi thu
        self.block = max(int(self.rate * BLOCK_S), 1)
        self.noise_floor = 1e-4
        self.level = 0.0         # độ to hiện tại (cho HUD vẽ)
        self.hearing = False     # đang có người nói (cho HUD vẽ)
        self.problem = ""        # lỗi micro để HUD báo lên màn hình
        self.pause_valid = False
        self.last_speech_level = 0.0   # độ to giọng câu vừa nghe (trước khi chỉnh to), cho tự học
        self._silent_blocks = 0
        self._queue: queue.Queue = queue.Queue()
        self._muted = False
        self._open()
        log(f"Micro: {dev['name']}")
        self.calibrate()

    def _open(self) -> None:
        self._last_audio = time.monotonic()
        self._stream = sd.InputStream(
            device=self.device, samplerate=self.rate, channels=1, dtype="float32",
            blocksize=self.block, callback=self._on_audio,
        )
        self._stream.start()

    def _reopen(self) -> None:
        """Micro tự dưng ngừng gửi âm thanh (hay gặp với tai nghe Bluetooth): mở lại."""
        log("🔄 Micro bị ngắt, đang kết nối lại...")
        with contextlib.suppress(Exception):
            self._stream.close()
        time.sleep(0.5)
        try:
            self._open()
        except sd.PortAudioError as e:
            log(f"⚠️  Chưa mở lại được micro: {e}")

    def _on_audio(self, indata, frames, time_info, status) -> None:
        self._last_audio = time.monotonic()
        if not self._muted:
            self._queue.put(indata[:, 0].copy())

    def calibrate(self) -> None:
        """Nghe thử nửa giây để biết phòng ồn cỡ nào, và phát hiện micro bị chặn.

        Gọi lại được khi nhạc vừa tắt: đo lúc nhạc đang phát thì tưởng phòng rất ồn, đặt ngưỡng
        cao quá, nói bình thường không vượt qua được."""
        levels, heard_anything = [], False
        deadline = time.monotonic() + 3.0
        while len(levels) < int(0.6 / BLOCK_S) and time.monotonic() < deadline:
            try:
                block = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            heard_anything = heard_anything or bool(np.any(block))
            levels.append(_rms(block))
        if not heard_anything:
            # Máy trả về toàn số 0 khi app chưa được cấp quyền micro.
            self.problem = MIC_BLOCKED
            log(f"⚠️  {MIC_BLOCKED}")
        if levels:
            self.noise_floor = min(max(float(np.median(levels)), 1e-6), MAX_FLOOR)

    @property
    def threshold(self) -> float:
        """Ngưỡng coi là có người nói: trên nền ồn 3 lần. Đã quen giọng bạn (tự học) thì hạ
        ngưỡng tối thiểu xuống còn ~1/3 độ to bạn hay nói, để giọng nhỏ vẫn nghe được."""
        floor = cfg.SPEECH_LEVEL
        typical = learn.typical_level()
        if typical:
            floor = min(floor, max(typical * 0.35, 0.003))
        return max(self.noise_floor * 3, floor)

    def flush(self) -> None:
        with contextlib.suppress(queue.Empty):
            while True:
                self._queue.get_nowait()

    @contextlib.contextmanager
    def paused(self, tail: float = 0.25):
        """Bịt tai trong lúc trợ lý xử lý và nói, để nó không tự nghe chính mình."""
        self._muted = True
        self.level, self.hearing = 0.0, False
        try:
            yield
        finally:
            time.sleep(tail)   # chờ tiếng loa tắt hẳn
            self.flush()
            self._muted = False

    def listen(self, timeout: float | None = None, meter: bool = False,
               on_pause=None) -> np.ndarray | None:
        """Chờ một câu nói, trả về âm thanh 16 kHz. Quá `timeout` giây không ai nói -> None.

        on_pause(âm thanh tới lúc đó) được gọi mỗi khi người nói vừa ngừng EARLY_S giây, để nhận
        dạng sẵn. Sau khi trả về, self.pause_valid = True nghĩa là từ lần gọi on_pause cuối người
        đó không nói thêm gì, kết quả nhận dạng sẵn dùng được luôn.
        """
        self.pause_valid = False
        self.last_speech_level = 0.0
        early_blocks = max(int(EARLY_S / BLOCK_S), 1)
        pre_roll = collections.deque(maxlen=int(PRE_ROLL_S / BLOCK_S))
        speech: list[np.ndarray] = []
        loud_run = quiet_run = 0
        deadline = time.monotonic() + timeout if timeout else None

        while True:
            try:
                block = self._queue.get(timeout=0.2)
            except queue.Empty:
                block = None
                if time.monotonic() - self._last_audio > 2.5:
                    self._reopen()
            if not speech and deadline and time.monotonic() > deadline:
                return None
            if block is None:
                continue

            level = self.level = _rms(block)
            # Toàn số 0 suốt 3 giây = micro bị chặn; có tiếng lại thì xoá cảnh báo.
            self._silent_blocks = 0 if np.any(block) else self._silent_blocks + 1
            if self._silent_blocks * BLOCK_S > 3 and not self.problem:
                self.problem = MIC_BLOCKED
                log(f"⚠️  {MIC_BLOCKED}")
            elif self._silent_blocks == 0 and self.problem:
                self.problem = ""
                log("✅ Micro đã có tiếng.")
            # Kẹp ở 2x để một câu nói không kéo nền ồn lên theo; nhạc nền kéo dài thì có.
            self.noise_floor += (1 - FLOOR_ALPHA) * (
                min(level, 2 * self.noise_floor) - self.noise_floor
            )
            self.noise_floor = max(self.noise_floor, 1e-6)
            threshold = self.threshold
            if meter:
                print(_meter(level, self.noise_floor, threshold), end="", flush=True)

            if not speech:
                pre_roll.append(block)
                loud_run = loud_run + 1 if level >= threshold else 0
                if loud_run * BLOCK_S >= START_S:
                    speech = list(pre_roll)
                    self.hearing = True
                continue

            speech.append(block)
            # "Im" là gần bằng nền ồn, để mấy chữ cuối nói nhỏ không bị coi là đã nói xong.
            quiet = level < max(self.noise_floor * 2.2, threshold * 0.6)
            quiet_run = quiet_run + 1 if quiet else 0
            duration = len(speech) * BLOCK_S
            if (on_pause and quiet_run == early_blocks
                    and duration - quiet_run * BLOCK_S >= MIN_UTTERANCE_S):
                on_pause(_boost(_to_whisper_rate(np.concatenate(speech), self.rate)))
            spoken = duration - quiet_run * BLOCK_S
            end_silence = LONG_END_SILENCE_S if spoken > LONG_SPEECH_S else END_SILENCE_S
            if quiet_run * BLOCK_S >= end_silence or duration >= MAX_UTTERANCE_S:
                self.hearing = False
                if spoken < MIN_UTTERANCE_S:
                    speech, loud_run, quiet_run = [], 0, 0   # tiếng động ngắn, bỏ qua
                    pre_roll.clear()
                    continue
                if meter:
                    print()
                self.pause_valid = quiet_run >= early_blocks
                levels = sorted(_rms(b) for b in speech)
                self.last_speech_level = levels[int(len(levels) * 0.8)]   # độ to lúc đang nói
                return _boost(_to_whisper_rate(np.concatenate(speech), self.rate))

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if x.size else 0.0


def _gibberish(text: str) -> bool:
    """Chữ "bịa" khi nghe tiếng ồn: ký tự không phải chữ Việt/Latin, hoặc một chữ lặp mãi."""
    for c in text:
        if c.isalpha() and not (ord(c) <= 0x24F or 0x1E00 <= ord(c) <= 0x1EFF):
            return True
    words = text.lower().split()
    return len(words) >= 8 and len(set(words)) <= len(words) / 4


def _boost(x: np.ndarray) -> np.ndarray:
    """Khuếch đại câu nói nhỏ (micro tai nghe, ngồi xa) cho Whisper nghe rõ; tối đa 30 lần."""
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    return x * min(0.6 / peak, 30.0) if peak > 0 else x


def _to_whisper_rate(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == WHISPER_RATE:
        return x.astype(np.float32)
    n = int(round(len(x) * WHISPER_RATE / rate))
    # Cắt bớt phổ rồi biến đổi ngược = hạ tần số lấy mẫu mà không bị méo tiếng.
    y = np.fft.irfft(np.fft.rfft(x)[: n // 2 + 1], n) * (n / len(x))
    return y.astype(np.float32)


def _meter(level: float, floor: float, threshold: float) -> str:
    bar = int(max(0.0, min(1.0, (math.log10(max(level, 1e-5)) + 4) / 4)) * 30)
    return (f"\r mức={level:.4f}  nền={floor:.4f}  ngưỡng={threshold:.4f}  "
            f"{'█' * bar}{'░' * (30 - bar)}")
