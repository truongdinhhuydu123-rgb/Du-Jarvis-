@echo off
chcp 65001 >nul
rem Chạy file này MỘT LẦN: sau đó gõ "run" để bật trợ lý, "turn off" để tắt
rem (trong cửa sổ lệnh, PowerShell; "run" gõ được cả ở Win + R).
rem Chuyển thư mục trợ lý sang chỗ khác thì chạy lại file này.
rem Gỡ lệnh: xoá 2 file run.cmd và turn.cmd trong %LOCALAPPDATA%\Microsoft\WindowsApps
set "DIR=%LOCALAPPDATA%\Microsoft\WindowsApps"
(
  echo @echo off
  echo call "%~dp0Start Tom.bat" %%*
) > "%DIR%\run.cmd"
if errorlevel 1 goto fail
(
  echo @echo off
  echo call "%~dp0Tat tro ly.bat" %%*
) > "%DIR%\turn.cmd"
if errorlevel 1 goto fail
echo Đã tạo lệnh "run" (bật trợ lý) và "turn off" (tắt trợ lý).
echo (Lệnh nằm ở: %DIR%)
pause
exit /b 0

:fail
echo Không tạo được lệnh.
pause
exit /b 1
