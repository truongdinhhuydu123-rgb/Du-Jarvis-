@echo off
rem Cho bot Telegram cua tro ly Du / Steve tu chay ngam (khong cua so) moi khi bat may,
rem va bat luon bay gio. Khong can mo tro ly ("run") ma van nhan tin Telegram duoc.
rem Go bo: bam dup "Tat chay ngam Telegram.bat".
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Chua cai thu vien: bam dup "Start Tom.bat" mot lan truoc, roi chay lai file nay.
  pause
  exit /b 1
)
powershell -NoProfile -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup') + '\Du-Steve Telegram.lnk'); $s.TargetPath = '%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments = 'jarvis.py --telegram'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'Bot Telegram cua tro ly Du / Steve'; $s.Save()"
if errorlevel 1 (
  echo Khong tao duoc loi tat chay khi bat may.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" jarvis.py --telegram
echo Da xong: bot Telegram dang chay ngam, va se tu chay moi khi bat may.
echo Nhat ky: .cache\tom.log   Tat: "Tat chay ngam Telegram.bat"
pause
