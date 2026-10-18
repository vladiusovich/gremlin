@echo off
rem Loads MITM_* settings from a profile in env\ into the caller's environment.
rem
rem   call lib\load-env.bat [NAME]
rem
rem With NAME, env\NAME.env must exist. Without NAME, env\default.env is loaded if present.
rem Format: KEY=VALUE per line, no spaces around "=", lines starting with # are comments.
rem Only the keys listed in ENV_KEYS are accepted (all optional), anything else is skipped
rem with a warning, so a typo is visible and a profile cannot clobber PATH, TEMP, etc.
rem A relative MITM_RULES is resolved against the project root.
rem Values are validated by the scripts that use them (lib\validate.bat).
rem Sets ENV_FILE to the loaded file (empty if none). Invoked via `call`, hence no setlocal.

rem Keep in sync with env\example.env and README.md
set "ENV_KEYS=MITM_URL MITM_BROWSER MITM_PORT MITM_RULES MITM_WEB MITM_INSECURE MITM_WIREGUARD MITM_WG_PORT"
for %%r in ("%~dp0..") do set "ENV_ROOT=%%~fr\"
set "ENV_FILE="
rem Drop MITM_* inherited from a parent script, so only the chosen profile applies
for /f "delims==" %%v in ('set MITM_ 2^>nul') do set "%%v="

if "%~1"=="" (
  if exist "%ENV_ROOT%env\default.env" set "ENV_FILE=%ENV_ROOT%env\default.env"
) else (
  if exist "%ENV_ROOT%env\%~1.env" (set "ENV_FILE=%ENV_ROOT%env\%~1.env") else if exist "%ENV_ROOT%env\%~1" set "ENV_FILE=%ENV_ROOT%env\%~1"
)
if not defined ENV_FILE (
  if "%~1"=="" exit /b 0
  echo [!!] Profile not found: env\%~1.env
  exit /b 1
)

for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ENV_FILE%") do (
  echo(%%a| findstr /x /i "%ENV_KEYS%" >nul && (set "%%a=%%~b") || echo [warn] %ENV_FILE%: unknown key "%%a" skipped. Allowed keys: %ENV_KEYS%
)

rem Substrings of an undefined variable break parsing, so skip via goto rather than `if defined`
if not defined MITM_RULES exit /b 0
if not "%MITM_RULES:~1,1%"==":" if not "%MITM_RULES:~0,2%"=="\\" set "MITM_RULES=%ENV_ROOT%%MITM_RULES%"
for %%f in ("%MITM_RULES%") do set "MITM_RULES=%%~ff"
exit /b 0
