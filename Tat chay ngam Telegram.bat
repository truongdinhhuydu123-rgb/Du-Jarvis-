@echo off
rem Tat bot Telegram dang chay ngam va bo tu chay khi bat may.
rem (Bot van chay cung tro ly khi ban go "run".)
powershell -NoProfile -Command "Remove-Item -ErrorAction SilentlyContinue ([Environment]::GetFolderPath('Startup') + '\Du-Steve Telegram.lnk'); Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -match 'jarvis\.py --telegram' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Da tat bot chay ngam va bo tu chay khi bat may.
pause
