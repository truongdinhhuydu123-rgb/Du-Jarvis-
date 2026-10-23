@echo off
chcp 65001 >nul
rem Double-click file này để bật Tom trên Windows.
rem Thiếu thư viện (lần đầu, hoặc giải nén chưa hết) thì tự cài, cần có mạng.
cd /d "%~dp0"
set PYTHONUTF8=1
set CHECK=import numpy, sounddevice, soundfile, faster_whisper, edge_tts, anthropic, google.genai, psutil, truststore, websockets

call :ok && goto run
echo Cài đặt lần đầu, chờ chút...
.venv\Scripts\python.exe -c "pass" 2>nul || call :fresh
call :install
call :ok && goto run
echo Thư viện bị thiếu hoặc hỏng, cài lại từ đầu (vài phút)...
call :fresh
call :install
call :ok && goto run
echo Cài đặt lỗi. Kiểm tra mạng rồi thử lại.
pause
exit /b 1

:run
.venv\Scripts\python.exe jarvis.py %*
pause
exit /b

rem --- các bước nhỏ ---
:ok
.venv\Scripts\python.exe -c "%CHECK%" 2>nul
exit /b

:fresh
if exist .venv rmdir /s /q .venv
py -3.11 -m venv .venv 2>nul || python -m venv .venv
exit /b

:install
.venv\Scripts\python.exe -m pip install -q --use-feature=truststore --upgrade pip 2>nul
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
exit /b
