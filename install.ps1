# Binder Jet Console — one-command operator install for Windows.
#   irm https://raw.githubusercontent.com/mattlmccoy/vention-printer-interface/main/install.ps1 | iex
# or, from a checkout:  .\install.ps1
# Idempotent: re-running updates the checkout, rebuilds, and restarts the always-on service.
# After it finishes, the operator runs in the background (Task Scheduler, at logon; restarts if it
# dies) at http://127.0.0.1:8020, and the GitHub Pages UI finds it automatically.
#
# Optional: .\install.ps1 -Ip 192.168.0.2 -JobsRoot "C:\MetPrint\Hot Folder"
param([string]$Ip = "", [string]$JobsRoot = "")
$ErrorActionPreference = "Stop"
$Repo = "https://github.com/mattlmccoy/vention-printer-interface.git"
$Dest = if ($env:VPI_HOME) { $env:VPI_HOME } else { Join-Path $HOME "vention-printer-interface" }
function Say($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }

Say "Tools (git, uv, node)"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is required: https://git-scm.com/download/win" }
if (-not (Get-Command uv  -ErrorAction SilentlyContinue)) { irm https://astral.sh/uv/install.ps1 | iex; $env:Path = "$HOME\.local\bin;$env:Path" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Write-Host "node not found — install Node.js (https://nodejs.org) if you want the UI served locally; the GitHub Pages site works regardless." }

Say "Checkout at $Dest"
if (Test-Path (Join-Path $Dest ".git")) { git -C $Dest pull --ff-only }
elseif ((Test-Path ".\backend\pyproject.toml") -and (Test-Path ".\.git")) { $Dest = (Get-Location).Path; Write-Host "using this checkout" }
else { git clone $Repo $Dest }

Say "Python environment (uv sync)"
Push-Location (Join-Path $Dest "backend"); uv sync --inexact -q; Pop-Location

Say "Frontend build"
if (Get-Command npm -ErrorAction SilentlyContinue) {
  Push-Location (Join-Path $Dest "frontend"); npm ci --silent; npm run build --silent; Pop-Location
  Write-Host "built frontend/dist"
} else { Write-Host "npm not found — skipped the local UI build (the GitHub Pages site still works)." }

Say "Background service (Task Scheduler, at logon)"
& (Join-Path $Dest "deploy\install-operator-service.ps1") -Ip $Ip -JobsRoot $JobsRoot

Say "Done"
Write-Host "The operator runs in the background at http://127.0.0.1:8020 (starts at logon, restarts if it dies)."
Write-Host "Open https://mattlmccoy.github.io/vention-printer-interface/ on this machine — it finds the operator by itself."
Write-Host "Re-run this command any time to update. Remove the service with deploy\uninstall-operator-service.ps1."
