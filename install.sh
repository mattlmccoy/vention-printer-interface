#!/usr/bin/env bash
# Binder Jet Console — one-command operator install for macOS + Linux.
#   curl -fsSL https://raw.githubusercontent.com/mattlmccoy/vention-printer-interface/main/install.sh | bash
# or, from a checkout:  ./install.sh
# Idempotent: re-running updates the checkout, rebuilds, and restarts the always-on service.
# After it finishes, the operator runs in the background (starts at login, restarts if it dies) at
# http://127.0.0.1:8020, and the GitHub Pages UI finds it automatically — exactly like FLIR / T&C.
#
# Optional env (pin a device / jobs folder into the service):
#   VPI_IP=192.168.0.2                      # attach the real MachineMotion at startup
#   VPI_JOBS_ROOT="/path/to/MetPrint Hot Folder"
set -euo pipefail

REPO="https://github.com/mattlmccoy/vention-printer-interface.git"
DEST="${VPI_HOME:-$HOME/vention-printer-interface}"
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
OS="$(uname -s)"

if [ "$OS" != "Darwin" ] && [ "$OS" != "Linux" ]; then
  echo "Use deploy\\install-operator-service.ps1 on Windows (see the README)." >&2; exit 1
fi

# ---- tools -------------------------------------------------------------------------------------
say "Tools (git, uv, node)"
if [ "$OS" = "Darwin" ]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required: https://brew.sh (install it, then re-run)." >&2; exit 1
  fi
  export HOMEBREW_NO_AUTO_UPDATE=1
  command -v git >/dev/null 2>&1 || xcode-select --install || true
  command -v uv  >/dev/null 2>&1 || brew install uv
  command -v node >/dev/null 2>&1 || brew install node
else
  sudo apt-get update -qq && sudo apt-get install -y -qq git curl nodejs npm 2>/dev/null || true
  command -v uv >/dev/null 2>&1 || (curl -LsSf https://astral.sh/uv/install.sh | sh)
  export PATH="$HOME/.local/bin:$PATH"
fi

# ---- checkout ----------------------------------------------------------------------------------
say "Checkout at $DEST"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --ff-only
elif [ -f "./backend/pyproject.toml" ] && [ -d "./.git" ]; then
  DEST="$(pwd)"; echo "using this checkout"
else
  git clone "$REPO" "$DEST"
fi

# ---- backend + frontend ------------------------------------------------------------------------
say "Python environment (uv sync)"
( cd "$DEST/backend" && uv sync --inexact -q )

say "Frontend build (the operator serves the built UI at :8020 too)"
if command -v npm >/dev/null 2>&1; then
  ( cd "$DEST/frontend" && npm ci --silent && npm run build --silent ) && echo "built frontend/dist"
else
  echo "node/npm not found — skipping the local UI build. The GitHub Pages site still works;"
  echo "install node and re-run if you also want the UI served from http://127.0.0.1:8020."
fi

# ---- always-on service -------------------------------------------------------------------------
if [ "$OS" = "Darwin" ]; then
  say "Background service (LaunchAgent, at login)"
  bash "$DEST/deploy/install-operator-service.sh"
else
  say "Background service (systemd --user, at login)"
  mkdir -p "$HOME/.config/systemd/user"
  UV_BIN="$(command -v uv)"
  EXTRA=""
  [ -n "${VPI_IP:-}" ] && EXTRA="$EXTRA --ip $VPI_IP"
  [ -n "${VPI_JOBS_ROOT:-}" ] && EXTRA="$EXTRA --jobs-root \"$VPI_JOBS_ROOT\""
  cat > "$HOME/.config/systemd/user/vpi-operator.service" <<UNIT
[Unit]
Description=Binder Jet Console operator
[Service]
WorkingDirectory=$DEST/backend
ExecStart=$UV_BIN run --directory $DEST/backend vpi-serve --host 127.0.0.1 --port 8020 --site-origin https://mattlmccoy.github.io$EXTRA
Restart=always
RestartSec=2
[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload && systemctl --user enable --now vpi-operator.service
  loginctl enable-linger "$USER" 2>/dev/null || true
fi

say "Done"
echo "The operator is running in the background at http://127.0.0.1:8020 (starts at login, restarts if it dies)."
echo "Open https://mattlmccoy.github.io/vention-printer-interface/ on this machine — it finds the operator by itself."
echo "Re-run this same command any time to update. Remove the service with deploy/uninstall-operator-service.sh."
