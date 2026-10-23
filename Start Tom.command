#!/bin/zsh
# Double-click file này để bật Tom.
# Lần đầu (hoặc khi thiếu thư viện) sẽ tự cài, cần có mạng.
cd "$(dirname "$0")" || exit 1

if ! .venv/bin/python -c "import numpy, sounddevice, soundfile, faster_whisper, edge_tts, anthropic, google.genai, psutil, truststore, mlx_whisper" 2>/dev/null; then
  echo "Cài đặt lần đầu, chờ chút..."
  python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt || {
    echo "Cài đặt lỗi. Kiểm tra mạng rồi thử lại."
    exit 1
  }
fi

exec .venv/bin/python jarvis.py "$@"
