@echo off
setlocal EnableExtensions
rem Installs mitmproxy (if missing) and adds its root CA to the current user's Trusted Root
rem Certification Authorities, so the browser accepts HTTPS through the proxy.
rem Safe to re-run: steps already done are skipped.

call "%~dp0lib\find-mitmdump.bat"
if defined MITMDUMP (
  echo [ok] mitmproxy is already installed: %MITMDUMP%
  goto :cert
)

echo [..] mitmproxy not found, installing via winget...
where winget >nul 2>nul
if not errorlevel 1 (
  winget install --id mitmproxy.mitmproxy -e --accept-package-agreements --accept-source-agreements
  call "%~dp0lib\find-mitmdump.bat"
)

if not defined MITMDUMP (
  where python >nul 2>nul
  if not errorlevel 1 (
    echo [..] winget failed, trying pip...
    python -m pip install --user --upgrade mitmproxy
    call "%~dp0lib\find-mitmdump.bat"
  )
)

if not defined MITMDUMP (
  echo [!!] Failed to install mitmproxy. Install it manually: https://mitmproxy.org/downloads/
  exit /b 1
)
echo [ok] mitmproxy installed: %MITMDUMP%

:cert
set "CA_CER=%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.cer"

if not exist "%CA_CER%" (
  echo [..] Generating the mitmproxy certificate...
  rem The CA is created on the proxy's first start: run it briefly on a free port, then kill it
  powershell -NoProfile -Command "$p = Start-Process -FilePath $env:MITMDUMP -ArgumentList '-p','0' -WindowStyle Hidden -PassThru; for($i=0; $i -lt 60 -and -not (Test-Path $env:CA_CER); $i++){ Start-Sleep -Milliseconds 500 }; Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue"
)
if not exist "%CA_CER%" (
  echo [!!] The certificate was not generated: %CA_CER%
  exit /b 1
)

rem Look up by thumbprint in both user and machine stores: the CA may have been regenerated
powershell -NoProfile -Command "$t = (New-Object Security.Cryptography.X509Certificates.X509Certificate2 $env:CA_CER).Thumbprint; foreach ($loc in 'CurrentUser','LocalMachine') { $s = New-Object Security.Cryptography.X509Certificates.X509Store 'Root', $loc; $s.Open('ReadOnly'); $found = $s.Certificates.Find('FindByThumbprint', $t, $false).Count; $s.Close(); if ($found) { exit 0 } }; exit 1"
if not errorlevel 1 (
  echo [ok] The mitmproxy certificate is already trusted.
  goto :done
)

echo [..] Adding the certificate to Trusted Root Certification Authorities (current user).
echo      Windows will show a security warning - answer "Yes".
certutil -user -addstore Root "%CA_CER%" >nul
if errorlevel 1 (
  echo [!!] Failed to add the certificate. To add it manually, open %CA_CER%
  exit /b 1
)
echo [ok] Certificate installed. Restart browsers that are already open.

:done
echo.
echo Done. To start the proxy and a browser through it: gremlin browser run
exit /b 0
