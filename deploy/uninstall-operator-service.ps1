# Stop and remove the Binder Jet Console operator scheduled task installed by install-operator-service.ps1.
$ErrorActionPreference = "SilentlyContinue"
$TaskName = "Binder Jet Console operator"
Stop-ScheduledTask -TaskName $TaskName
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed '$TaskName' (the operator will no longer auto-start at logon)."
