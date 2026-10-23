"""Tạo bản bot Google "dán sẵn" (bot-telegram-DAN-VAO.gs): điền token, key, mật khẩu từ .env và
mô tả riêng (FOCUS trong config_rieng.py) vào bot-telegram.gs. File tạo ra chứa thông tin riêng nên
không đưa lên GitHub (.gitignore).

Chạy:  .venv\\Scripts\\python.exe google-cloud\\tao_ban_dan_vao.py
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402  (đã gộp config_rieng.py)


def main() -> None:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("'\"")
    fills = {
        "DAN-TOKEN-BOT-TELEGRAM": env.get("TELEGRAM_BOT_TOKEN", ""),
        "DAN-CHAT-ID-CUA-BAN": env.get("TELEGRAM_CHAT_ID", ""),
        "DAN-KEY-GEMINI": env.get("GEMINI_API_KEY", ""),
        "DAT-MOT-MAT-KHAU-RIENG": env.get("GAS_BOT_SECRET", ""),
        "DAN-GCAL_SECRET-TRONG-.env": env.get("GCAL_SECRET", ""),
    }
    missing = [k for k, v in fills.items() if not v and k != "DAN-GCAL_SECRET-TRONG-.env"]
    if missing:
        sys.exit("Thiếu trong .env: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / GEMINI_API_KEY / GAS_BOT_SECRET")
    code = (HERE / "bot-telegram.gs").read_text(encoding="utf-8")
    for placeholder, value in fills.items():
        code = code.replace(f'"{placeholder}"', json.dumps(value))
    focus = "const FOCUS = " + json.dumps(" ".join(config.FOCUS.split()), ensure_ascii=False) + ";\n"
    code = re.sub(r"const FOCUS = [\s\S]*?;\n", lambda m: focus, code, count=1)
    out = HERE / "bot-telegram-DAN-VAO.gs"
    out.write_text("// BẢN RIÊNG CỦA BẠN (đã điền token, key, mật khẩu): dán nguyên file này vào Apps Script. "
                   "ĐỪNG chia sẻ.\n" + code, encoding="utf-8")
    print(f"Đã tạo {out.name} ({len(code)} ký tự).")


if __name__ == "__main__":
    main()
