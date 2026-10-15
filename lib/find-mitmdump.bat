@echo off
rem Finds mitmdump.exe and stores its full path in MITMDUMP (empty if not found).
rem Invoked via `call` from other scripts, hence no setlocal.
set "MITMDUMP="

for /f "delims=" %%i in ('where mitmdump 2^>nul') do if not defined MITMDUMP set "MITMDUMP=%%i"
if defined MITMDUMP exit /b 0

rem The installer (winget / mitmproxy.org) puts it here, but PATH in the current console may be stale
for %%p in ("%ProgramFiles%\mitmproxy\bin\mitmdump.exe" "%LOCALAPPDATA%\Programs\mitmproxy\bin\mitmdump.exe") do (
  if exist %%p if not defined MITMDUMP set "MITMDUMP=%%~p"
)
if defined MITMDUMP exit /b 0

rem pip install: Scripts folders of the current Python (global and --user)
for /f "delims=" %%d in ('python -c "import sysconfig,site,os;print(sysconfig.get_path('scripts'));print(os.path.join(os.path.dirname(site.getusersitepackages()),'Scripts'))" 2^>nul') do (
  if exist "%%d\mitmdump.exe" if not defined MITMDUMP set "MITMDUMP=%%d\mitmdump.exe"
)
exit /b 0
