@echo off
rem Tat tro ly Du / Steve: bam dup file nay, hoac go  turn off  trong PowerShell / cua so lenh
rem (lenh "turn" duoc tao boi "Tao lenh run.bat").
rem Tro ly thay file .cache\stop thi noi loi chao roi tat, dong luon man hinh HUD.
if "%~1"=="" goto stop
if /i "%~1"=="off" goto stop
if /i "%~1"=="of" goto stop
echo Cach dung: turn off   (tat tro ly Du / Steve)
exit /b 1

:stop
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'jarvis\.py' }) { exit 0 } else { exit 1 }"
if errorlevel 1 (
  echo Tro ly Du / Steve dang khong chay.
  exit /b 0
)
if not exist "%~dp0.cache" mkdir "%~dp0.cache"
type nul > "%~dp0.cache\stop"
echo Da gui lenh tat. Du / Steve se chao roi tat trong vai giay.
