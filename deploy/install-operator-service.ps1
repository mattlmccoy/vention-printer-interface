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

# Resolve the sliced-jobs Hot Folder. This repo is often a standalone clone OUTSIDE Dropbox, so
# vpi-serve cannot find the shared Dropbox Hot Folder on its own (its script-relative default only
# works when the code lives inside Dropbox, i.e. on the Mac). The service MUST therefore pass an
# explicit --jobs-root. When -JobsRoot isn't given, auto-detect the per-user Dropbox Hot Folder.
if (-not $JobsRoot) {
  $auto = Join-Path $env:USERPROFILE "GaTech Dropbox\Matthew McCoy\mattmccoy-research\research\binderjet\code\rfam-web\Hot Folder"
  if (Test-Path $auto) {
    $JobsRoot = $auto
    Write-Host "Auto-detected sliced-jobs Hot Folder: $JobsRoot"
  } else {
    Write-Warning "No -JobsRoot given and the default Dropbox Hot Folder was not found at:`n  $auto`nThe operator would fall back to backend\jobs (empty). Re-run with -JobsRoot `"<path to Hot Folder>`"."
  }
} elseif (-not (Test-Path $JobsRoot)) {
  Write-Warning "The -JobsRoot path does not exist yet (Dropbox not synced?): $JobsRoot"
}

# Build the vpi-serve argument string.
$argLine = "run --directory `"$BackendDir`" vpi-serve --host 127.0.0.1 --port $Port"
if ($SiteOrigin) { $argLine += " --site-origin $SiteOrigin" }
if ($Ip)         { $argLine += " --ip $Ip" }
if ($JobsRoot)   { $argLine += " --jobs-root `"$JobsRoot`"" }

$action   = New-ScheduledTaskAction -Execute $uv -Argument $argLine -WorkingDirectory $BackendDir
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

# Free port $Port so the fresh task binds cleanly (a manually-started vpi-serve or a prior task run
# would otherwise hold it and the new instance would fail with WinError 10048).
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed + started '$TaskName'"
Write-Host "  serves: http://127.0.0.1:$Port  (boots idle - connect the MachineMotion from the UI connect popover)"
Write-Host "  the GitHub Pages site (https://mattlmccoy.github.io/vention-printer-interface/) will now reach this operator."
Write-Host "Stop/remove it any time with: .\uninstall-operator-service.ps1"
