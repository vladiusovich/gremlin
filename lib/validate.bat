@echo off
rem Validates a setting value; prints an error and exits with 1 if it is invalid.
rem
rem   call lib\validate.bat port VALUE        1-65535
rem   call lib\validate.bat bool NAME VALUE   empty, 1/0, true/false, yes/no, on/off
rem
rem URLs are validated inline by the callers: passing them through `call` would
rem re-expand %XX escapes.
goto :%~1

:port
set "V_PORT=%~2"
echo(%V_PORT%| findstr /r /x "[1-9][0-9]*" >nul || goto :port_bad
if not "%V_PORT:~5%"=="" goto :port_bad
if %V_PORT% GTR 65535 goto :port_bad
exit /b 0
:port_bad
echo [!!] Invalid port "%~2": must be a number 1-65535 (option -p or MITM_PORT in the profile)
exit /b 1

:bool
if "%~3"=="" exit /b 0
for %%v in (0 1 true false yes no on off) do if /i "%~3"=="%%v" exit /b 0
echo [!!] Invalid value %~2="%~3": must be 1 or 0 (or true/false, yes/no, on/off)
exit /b 1
