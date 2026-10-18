@echo off
setlocal EnableExtensions
rem Sets gremlin up on Windows: Python 3.10+ (asks before installing it with winget), then
rem "gremlin install" in Python: mitmproxy (asks too) and trust in its certificate.
rem Safe to re-run: steps already done are skipped.
rem
rem   install.bat [-y]       -y answers yes to every question

set "ROOT=%~dp0"
set "YES="
for %%a in (%*) do (
  if /i "%%~a"=="-y" set "YES=1"
  if /i "%%~a"=="--yes" set "YES=1"
)

call "%ROOT%lib\find-python.bat"
if defined PYTHON (
  echo [ok] Python: %PYTHON%
  goto :run
)

echo [..] Python 3.10 or newer is not installed. gremlin's commands are written in Python.
where winget >nul 2>nul || (
  echo [!!] winget is not available to install it. Install Python from https://www.python.org/downloads/
  echo      ^(tick "Add python.exe to PATH"^) and run install.bat again.
  goto :fail
)
if defined YES (
  echo [??] Install Python 3.12 now with winget? [Y/N] Y ^(-y^)
) else (
  choice /c YN /m "[??] Install Python 3.12 now with winget?"
  if errorlevel 2 (
    echo [!!] Python is required. Install it from https://www.python.org/downloads/ and run install.bat again.
    goto :fail
  )
)
winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
call "%ROOT%lib\find-python.bat"
if not defined PYTHON (
  echo [!!] Failed to install Python. Install it from https://www.python.org/downloads/ and run install.bat again.
  goto :fail
)
echo [ok] Python installed: %PYTHON%

:run
"%PYTHON%" "%ROOT%lib\main.py" install %*
set "CODE=%errorlevel%"
goto :end

:fail
set "CODE=1"

:end
rem Started by a double-click: keep the window open, so the result can be read
call :double_clicked && pause
exit /b %CODE%

:double_clicked
rem The first ancestor that is not cmd.exe is Explorer: the window closes as soon as the script ends.
rem From cmd, PowerShell or VS Code it is not, and the console stays open anyway.
powershell -NoProfile -Command "$p = $PID; do { $p = (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $p)).ParentProcessId; $n = (Get-Process -Id $p -ErrorAction SilentlyContinue).Name } while ($n -eq 'cmd'); if ($n -eq 'explorer') { exit 0 } else { exit 1 }" >nul 2>nul
