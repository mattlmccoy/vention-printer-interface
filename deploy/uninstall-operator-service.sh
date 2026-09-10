#!/usr/bin/env bash
# Stop and remove the Binder Jet Console operator LaunchAgent installed by install-operator-service.sh.
set -euo pipefail

LABEL="com.binderjet.operator"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
GUI="gui/$(id -u)"

launchctl bootout "$GUI/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "Removed $LABEL (the operator will no longer auto-start). Log kept at ~/Library/Logs/binderjet-operator.log"
