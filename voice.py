"""Giọng nói của trợ lý: chữ -> giọng đọc -> hiệu ứng trầm, vang -> loa.

Thứ tự ưu tiên giọng đọc:
  1. ElevenLabs   nếu có key trong .env (hay nhất, giống video)
  2. Microsoft    giọng neural miễn phí, cần mạng (config.VOICE)
  3. Máy          giọng có sẵn của macOS/Windows, không cần mạng (config.OFFLINE_VOICES)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import uuid
import urllib.request
import wave
from pathlib import Path

import numpy as np

import config as cfg
from common import CACHE, MAC, lang, log, run

FX_RATE = 44100
# Windows: đọc câu bằng giọng có sẵn của máy (SAPI) ra file WAV. Chữ truyền qua biến môi
# trường chứ không ghép vào lệnh, để câu có dấu nháy hay ký tự lạ không phá được lệnh.
WINDOWS_TTS_PS = """\
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like "$env:TOM_LANG*" } |
     Select-Object -First 1
if (-not $v) {   # máy không có giọng cho tiếng này: thà im còn hơn đọc tiếng Việt bằng giọng Anh
  [Console]::Error.WriteLine("Windows has no installed voice for language '$env:TOM_LANG'")
  exit 1
}
$s.SelectVoice($v.VoiceInfo.Name)
$s.Rate = [int]$env:TOM_RATE
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(44100, 'Sixteen', 'Mono')
$s.SetOutputToWaveFile($env:TOM_OUT, $fmt)
$s.Speak($env:TOM_TEXT)
$s.Dispose()
"""
TEMP_PREFIX = "tmp_"   # giọng tạo một lần, phát xong là xoá
listeners: list = []   # hàm(event, text) được gọi khi bắt đầu ("start") và nói xong ("end")
_speaking = threading.Lock()   # mỗi lúc chỉ đọc một câu
EQ_POINTS = np.array([   # (tần số Hz, tăng/giảm dB): ấm vừa phải, rõ lời trên loa laptop
    (20, -24), (80, -8), (130, 0), (220, 2), (400, 0),
    (1000, 0), (2500, 3), (4000, 4), (6000, 3), (9000, 0), (20000, -6),
], dtype=float)


def jarvis_fx(x: np.ndarray, pitch: float, reverb: float, metal: float = 0.0,
              loudness: float = 3.0) -> np.ndarray:
    """Làm giọng trầm, ấm và hơi vang kiểu trợ lý AI trong phim."""
    # 1. Hạ tông: kéo dãn tín hiệu nên giọng vừa trầm vừa "dày" hơn.
    #    Giọng bị chậm đi theo; lúc tạo giọng đã cho đọc nhanh hơn để bù.
    x = np.interp(np.arange(0, len(x) - 1, 2 ** (pitch / 12)), np.arange(len(x)), x)

    # 1b. Âm sắc "máy": trộn thêm chính nó trễ 9 ms, tạo tiếng vang kim loại rất ngắn.
    if metal > 0:
        delay = int(0.009 * FX_RATE)
        x = x + metal * np.concatenate([np.zeros(delay), x[:-delay]])

    # 2. EQ: cắt ù dưới 80 Hz, thêm chút ấm ở 200 Hz, thêm nét ở 2.5-6 kHz cho rõ lời.
    freqs = np.fft.rfftfreq(len(x), 1 / FX_RATE)
    gain_db = np.interp(np.log10(np.maximum(freqs, 1.0)),
                        np.log10(EQ_POINTS[:, 0]), EQ_POINTS[:, 1])
    x = np.fft.irfft(np.fft.rfft(x) * 10 ** (gain_db / 20), len(x))

    # 3. Vang: nhân chập với tiếng vọng của một căn phòng nhỏ (nhiễu tắt dần 0.35 s).
    if reverb > 0:
        n = int(0.35 * FX_RATE)
        ir = np.random.default_rng(7).standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)
        ir[: int(0.012 * FX_RATE)] = 0.0
        size = 1 << (len(x) + n - 1).bit_length()
        ir_spec = np.fft.rfft(ir, size)
        ir_spec /= 1 + (np.fft.rfftfreq(size, 1 / FX_RATE) / 4000) ** 2   # vang không chói
        wet = np.fft.irfft(np.fft.rfft(x, size) * ir_spec, size)[: len(x) + n - 1]
        dry_rms, wet_rms = np.sqrt(np.mean(x * x)), np.sqrt(np.mean(wet * wet))
        x = np.pad(x, (0, n - 1))
        if wet_rms > 0:
            x = x + reverb * wet * (dry_rms / wet_rms)

    # 4. Chuẩn hoá rồi nén tiếng: chỗ nhỏ được kéo lên, giọng to đều mà không vỡ.
    peak = np.max(np.abs(x))
    if peak > 0:
        x = np.tanh(loudness * x / peak) / np.tanh(loudness) * 0.97
    return x


def _voices() -> tuple[str, str]:
    """(giọng Microsoft, giọng macOS dự phòng) cho tiếng đang dùng."""
    return (cfg.VOICES.get(lang(), cfg.VOICES["vi"]),
            cfg.OFFLINE_VOICES.get(lang(), cfg.OFFLINE_VOICES["vi"]))


def _speedup() -> float:
    """Phải đọc nhanh hơn bao nhiêu lần để bù phần bị chậm do hạ tông."""
    return cfg.VOICE_SPEED * 2 ** (-cfg.VOICE_PITCH / 12)


def _microsoft_voice(text: str, raw: Path) -> bool:
    import edge_tts

    mp3 = raw.with_suffix(".mp3")
    rate = f"{round((_speedup() - 1) * 100):+d}%"
    # Dịch vụ thỉnh thoảng không trả âm thanh (giọng tiếng Việt bị khoảng 1/4 số lần): thử lại.
    tries = 4
    for attempt in range(tries):
        try:
            edge_tts.Communicate(text, _voices()[0], rate=rate).save_sync(str(mp3))
            break
        except Exception as e:   # mất mạng, sai tên giọng, dịch vụ đổi... -> giọng của máy
            if attempt == tries - 1:
                log(f"⚠️  Giọng {_voices()[0]} lỗi ({e}); dùng tạm giọng có sẵn của máy.")
                return False
            time.sleep(0.3)
    return _to_wav(mp3, raw)


def _to_wav(src: Path, dst: Path) -> bool:
    """mp3 -> WAV một kênh 44.1 kHz để thêm hiệu ứng."""
    if MAC:
        return run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{FX_RATE}", "-c", "1",
                    str(src), str(dst)])
    import soundfile as sf

    try:
        x, rate = sf.read(str(src), dtype="float64", always_2d=True)
    except (OSError, RuntimeError) as e:
        log(f"⚠️  Không đọc được {src.name}: {e}")
        return False
    x = x.mean(axis=1)
    if rate != FX_RATE:
        x = np.interp(np.arange(0, len(x), rate / FX_RATE), np.arange(len(x)), x)
    sf.write(str(dst), x, FX_RATE, subtype="PCM_16")
    return True


def _offline_voice(text: str, raw: Path) -> bool:
    if MAC:
        return run(["say", "-v", _voices()[1], "-r", str(round(175 * _speedup())),
                    "-o", str(raw), f"--data-format=LEI16@{FX_RATE}", text])
    # Windows: tốc độ SAPI từ -10 đến 10
    env = dict(os.environ, TOM_TEXT=text, TOM_OUT=str(raw), TOM_LANG=_voices()[1],
               TOM_RATE=str(max(-10, min(10, round((_speedup() - 1) * 10)))))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", WINDOWS_TTS_PS], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        log(f"⚠️  Giọng có sẵn của Windows: {r.stderr.strip() or 'lỗi'}")
    return r.returncode == 0


def _play(audio: Path) -> None:
    if MAC:
        run(["afplay", str(audio)])
        return
    import sounddevice as sd
    import soundfile as sf

    try:
        data, rate = sf.read(str(audio), dtype="float32", always_2d=True)
        with sd.OutputStream(samplerate=rate, channels=data.shape[1], dtype="float32") as out:
            out.write(data)   # thoát khối "with" sẽ chờ phát hết rồi mới đóng
    except (OSError, RuntimeError, sd.PortAudioError) as e:
        log(f"⚠️  Không phát được âm thanh: {e}")


def _apply_fx(raw: Path, out: Path) -> bool:
    try:
        with wave.open(str(raw), "rb") as wf:
            x = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2") / 32768.0
        if x.size < 2:
            return False
        y = jarvis_fx(x, cfg.VOICE_PITCH, cfg.VOICE_REVERB, cfg.VOICE_METAL, cfg.VOICE_LOUDNESS)
        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(FX_RATE)
            wf.writeframes((y * 32767).astype("<i2").tobytes())
    except (OSError, EOFError, wave.Error) as e:
        log(f"⚠️  Không xử lý được giọng nói: {e}")
        return False
    return True


def _elevenlabs(text: str, out: Path, api_key: str, voice_id: str) -> bool:
    model = os.environ.get("ELEVENLABS_MODEL_ID", "").strip() or "eleven_flash_v2_5"
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/text-to-speech/"
        f"{urllib.parse.quote(voice_id, safe='')}?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": model}).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            audio = resp.read()
    except OSError as e:   # gồm cả lỗi mạng, sai key, hết quota
        log(f"⚠️  ElevenLabs lỗi: {e}")
        return False
    if not audio:
        return False
    out.write_bytes(audio)
    return True


def synthesize(text: str, keep: bool = False) -> Path | None:
    """Tạo file âm thanh cho một câu. keep=True thì lưu lại để lần sau phát ngay."""
    CACHE.mkdir(exist_ok=True)
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    settings = (text, *_voices(), cfg.VOICE_PITCH, cfg.VOICE_REVERB,
                cfg.VOICE_METAL, cfg.VOICE_LOUDNESS, cfg.VOICE_SPEED, voice_id, "eq2")
    # Tên file riêng cho từng lần để hai câu tạo cùng lúc (luồng khác nhau) không ghi đè nhau.
    name = (hashlib.sha256(repr(settings).encode()).hexdigest()[:20] if keep
            else f"{TEMP_PREFIX}{uuid.uuid4().hex[:8]}")

    for ext in ("mp3", "wav"):
        saved = CACHE / f"say_{name}.{ext}"
        if keep and saved.is_file():
            saved.touch()   # đánh dấu vừa dùng, để dọn cache không xoá nhầm
            return saved

    if api_key and voice_id:
        out = CACHE / f"say_{name}.mp3"
        if _elevenlabs(text, out, api_key, voice_id):
            return out

    raw, out = CACHE / f"raw_{uuid.uuid4().hex[:8]}.wav", CACHE / f"say_{name}.wav"
    try:
        ok = ("Neural" in _voices()[0] and _microsoft_voice(text, raw)) or _offline_voice(text, raw)
        if not ok:
            return None
        if not (cfg.VOICE_PITCH or cfg.VOICE_REVERB or cfg.VOICE_METAL):
            raw.replace(out)
            return out
        return out if _apply_fx(raw, out) else None
    finally:
        for leftover in (raw, raw.with_suffix(".mp3")):
            leftover.unlink(missing_ok=True)


def warm_up(phrases: list[str]) -> None:
    """Tạo sẵn (ở luồng nền) giọng cho các câu hay dùng, để lúc cần là phát ngay."""
    def work() -> None:
        for phrase in phrases:
            synthesize(clean_for_speech(phrase), keep=True)
    threading.Thread(target=work, daemon=True).start()


def prune_cache(days: int = 30) -> None:
    """Xoá giọng đã lưu mà lâu không dùng, cùng file tạm còn sót."""
    cutoff = time.time() - days * 86400
    for f in list(CACHE.glob("say_*")) + list(CACHE.glob("raw*")):
        if f.name.startswith(f"say_{TEMP_PREFIX}") or f.name.startswith("raw") \
                or f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def chime() -> None:
    """Tiếng "tíng" nhỏ báo đã nhận lệnh (phát ngầm, không phải chờ)."""
    if not (cfg.ACK_SOUND and Path(cfg.ACK_SOUND).is_file()):
        return
    if MAC:
        subprocess.Popen(["afplay", cfg.ACK_SOUND],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        import winsound

        winsound.PlaySound(cfg.ACK_SOUND, winsound.SND_FILENAME | winsound.SND_ASYNC
                           | winsound.SND_NODEFAULT)


def clean_for_speech(text: str) -> str:
    """Bỏ ký hiệu markdown và link để máy không đọc lên thành "sao sao" hay "h t t p"."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>|~]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def speak(text: str, keep: bool = False, dry_run: bool = False) -> None:
    text = clean_for_speech(text)
    if not text:
        return
    print(f"   🔊 {text}", flush=True)
    audio = None
    if not dry_run:
        audio = synthesize(text, keep)
        if audio is None:   # vẫn báo cho HUD để câu trả lời hiện lên màn hình
            log("⚠️  Không tạo được giọng nói, chỉ hiện chữ.")
    with _speaking:   # câu "chờ vài giây" đang đọc dở thì câu trả lời đợi đọc xong
        for listener in listeners:
            listener("start", text)
        try:
            if audio:
                _play(audio)
        finally:
            if audio and audio.name.startswith(f"say_{TEMP_PREFIX}"):
                audio.unlink(missing_ok=True)
            for listener in listeners:
                listener("end", text)
