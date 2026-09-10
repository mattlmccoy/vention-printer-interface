# Install the Binder Jet Console operator as an always-on Windows background service
# (Task Scheduler, at logon). After this, `vpi-serve` starts automatically at logon, restarts if it
# dies, and is always reachable at http://127.0.0.1:8020 — so the web UI (local or the GitHub Pages
# site) always finds it, exactly like the FLIR and T&C tools. Reversible with uninstall-operator-service.ps1.
#
# Boots IDLE by default (no device): open the UI and connect the MachineMotion at runtime.
# Override with params, e.g.:  .\install-operator-service.ps1 -Port 8020 -Ip 192.168.0.2 -JobsRoot "C:\MetPrint\Hot Folder"
param(
  [int]$Port = 8020,
  [string]$SiteOrigin = "https://mattlmccoy.github.io",
  [string]$Ip = "",
  [string]$JobsRoot = ""
)
$ErrorActionPreference = "Stop"
$TaskName = "Binder Jet Console operator"

$BackendDir = (Resolve-Path (Join-Path $PSScriptRoot "..\backend")).Path
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { throw "'uv' not found on PATH. Install uv first (https://docs.astral.sh/uv/)." }

# Build the vpi-serve argument string.
$argLine = "run --directory `"$BackendDir`" vpi-serve --host 127.0.0.1 --port $Port"
if ($SiteOrigin) { $argLine += " --site-origin $SiteOrigin" }
if ($Ip)         { $argLine += " --ip $Ip" }
if ($JobsRoot)   { $argLine += " --jobs-root `"$JobsRoot`"" }

$action   = New-ScheduledTaskAction -Execute $uv -Argument $argLine -WorkingDirectory $BackendDir
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed + started '$TaskName'"
Write-Host "  serves: http://127.0.0.1:$Port  (boots idle — connect the MachineMotion from the UI's connect popover)"
Write-Host "  the GitHub Pages site (https://mattlmccoy.github.io/vention-printer-interface/) will now reach this operator."
Write-Host "Stop/remove it any time with: .\uninstall-operator-service.ps1"
