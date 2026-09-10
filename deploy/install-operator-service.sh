#!/usr/bin/env bash
# Install the Binder Jet Console operator as an always-on macOS background service (LaunchAgent).
#
# After this, `vpi-serve` starts automatically at login, restarts if it dies, and is always reachable
# at http://127.0.0.1:8020 — so the web UI (local or the GitHub Pages site) always finds it and
# settings always save, exactly like the FLIR and T&C tools. Reversible with ./uninstall-operator-service.sh.
#
# Boots IDLE by default (no device): open the UI and use the connect popover to attach the
# MachineMotion at runtime. Override via env before running:
#   VPI_PORT=8020                                  # operator port
#   VPI_SITE_ORIGIN=https://mattlmccoy.github.io   # origin allowed to control it cross-origin ('' to disable)
#   VPI_IP=192.168.0.2                             # pin the real MachineMotion at startup (implies backend machinemotion)
#   VPI_JOBS_ROOT="/path/to/MetPrint Hot Folder"   # scan this folder for sliced jobs
set -euo pipefail

LABEL="com.binderjet.operator"
PORT="${VPI_PORT:-8020}"
SITE_ORIGIN="${VPI_SITE_ORIGIN-https://mattlmccoy.github.io}"

# Resolve paths from this script's location (portable — no hardcoded home path).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../backend" && pwd)"
UV_BIN="$(command -v uv || true)"
if [[ -z "$UV_BIN" ]]; then
  echo "error: 'uv' not found on PATH. Install uv first (https://docs.astral.sh/uv/)." >&2
  exit 1
fi
UV_DIR="$(dirname "$UV_BIN")"

AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENTS_DIR/$LABEL.plist"
LOG="$HOME/Library/Logs/binderjet-operator.log"
mkdir -p "$AGENTS_DIR" "$(dirname "$LOG")"

# Build ProgramArguments: uv run vpi-serve --host 127.0.0.1 --port N [--site-origin ..] [--ip ..] [--jobs-root ..]
ARGS=("<string>$UV_BIN</string>" "<string>run</string>" "<string>vpi-serve</string>"
      "<string>--host</string>" "<string>127.0.0.1</string>"
      "<string>--port</string>" "<string>$PORT</string>")
if [[ -n "$SITE_ORIGIN" ]]; then
  ARGS+=("<string>--site-origin</string>" "<string>$SITE_ORIGIN</string>")
fi
if [[ -n "${VPI_IP:-}" ]]; then
  ARGS+=("<string>--ip</string>" "<string>$VPI_IP</string>")
fi
if [[ -n "${VPI_JOBS_ROOT:-}" ]]; then
  ARGS+=("<string>--jobs-root</string>" "<string>$VPI_JOBS_ROOT</string>")
fi
PROGRAM_ARGS="$(printf '        %s\n' "${ARGS[@]}")"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>            <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
$PROGRAM_ARGS    </array>
    <key>WorkingDirectory</key> <string>$BACKEND_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key> <string>$UV_DIR:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>        <true/>
    <key>KeepAlive</key>        <true/>
    <key>StandardOutPath</key>  <string>$LOG</string>
    <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST

# (Re)load it. bootstrap/bootout are the modern launchctl verbs; fall back to load/unload.
GUI="gui/$(id -u)"
launchctl bootout "$GUI/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
launchctl bootstrap "$GUI" "$PLIST" 2>/dev/null || launchctl load "$PLIST"

echo "Installed + started $LABEL"
echo "  plist:  $PLIST"
echo "  log:    $LOG"
echo "  serves: http://127.0.0.1:$PORT  (boots idle — connect the MachineMotion from the UI's connect popover)"
echo "  the GitHub Pages site (https://mattlmccoy.github.io/vention-printer-interface/) will now reach this operator."
echo "Stop/remove it any time with: $SCRIPT_DIR/uninstall-operator-service.sh"
