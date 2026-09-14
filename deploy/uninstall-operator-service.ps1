# Stop and remove the Binder Jet Console operator scheduled task installed by install-operator-service.ps1.
param([int]$Port = 8020)
$ErrorActionPreference = "SilentlyContinue"
$TaskName = "Binder Jet Console operator"
Stop-ScheduledTask -TaskName $TaskName
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
# Also free the port in case the served process is still bound to it.
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Write-Host "Removed '$TaskName' (the operator will no longer auto-start at logon)."
