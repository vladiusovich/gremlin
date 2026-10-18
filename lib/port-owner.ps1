# Tells what listens on a TCP port, for lib\gremlin_cli\ports.py on Windows. Prints one line:
#
#   free                   nothing listens on the port
#   busy                   something listens (only without -Rules)
#   same                   a gremlin proxy with the rules file -Rules
#   other-rules <file>     a gremlin proxy with another rules file
#   other <process>        some other program
#
# Checks the listening sockets rather than connecting to the port: a connect also fails
# when the program on the port is busy or frozen, and the port would be reported free.
param([Parameter(Mandatory)][int]$Port, [string]$Rules)

$listening = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
    Where-Object Port -eq $Port
if (-not $listening) { 'free'; exit 0 }
if (-not $Rules) { 'busy'; exit 0 }

$conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
$proc = if ($conn) { Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" }
if (-not $proc) { 'other an unknown process'; exit 0 }
# gremlin proxy run always passes --set "rules_file=...", that is how its proxy is recognized
if ($proc.CommandLine -notmatch 'rules_file=([^"]+)') { "other $($proc.Name) (PID $($proc.ProcessId))"; exit 0 }
$running = $Matches[1].Trim()
if ([IO.Path]::GetFullPath($running) -ieq [IO.Path]::GetFullPath($Rules)) { 'same' } else { "other-rules $running" }
exit 0
