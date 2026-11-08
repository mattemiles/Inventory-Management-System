@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install 64-bit Python 3.12 from python.org first.
  pause
  exit /b 1
)
py -3.12 -c "import struct; assert struct.calcsize('P') == 8, '64-bit Python is required'"
if errorlevel 1 (
  echo Install the standard 64-bit Python 3.12 distribution including the py launcher.
  pause
  exit /b 1
)
if not exist ".build-venv\Scripts\python.exe" (
  py -3.12 -m venv .build-venv
  if errorlevel 1 goto failed
)
".build-venv\Scripts\python.exe" tools\build_windows.py
if errorlevel 1 goto failed
echo.
echo Build complete. See the output folder for your Setup EXE and SHA256 file.
echo Complete WINDOWS_CHECKLIST.txt before publishing the installer.
pause
exit /b 0
:failed
echo.
echo Build stopped. No new installer has been approved for distribution.
echo Read the error above, or send it to Matt for troubleshooting.
pause
exit /b 1
