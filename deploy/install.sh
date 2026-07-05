#!/usr/bin/env bash
# Aeon-V2 installer for the T5810 (or any Linux host with Python 3.11+ & Node 18+).
# Idempotent: safe to re-run to update.
set -euo pipefail

REPO_DIR="${AEON_REPO_DIR:-$HOME/Aeon-V2}"
DATA_DIR="${AEON_DATA_DIR:-$HOME/aeon-data}"
SYSTEMD_DIR="$HOME/.config/systemd/user"

echo "==> Aeon-V2 install"
echo "    repo: $REPO_DIR"
echo "    data: $DATA_DIR"

cd "$REPO_DIR"

echo "==> Python venv + server package"
python3 -m venv server/.venv
server/.venv/bin/pip install -q --upgrade pip
server/.venv/bin/pip install -q -e server/

echo "==> Data root"
export AEON_DATA_DIR="$DATA_DIR"
server/.venv/bin/aeon-init-data
if [ ! -f "$DATA_DIR/aeon.env" ]; then
  # aeon.env holds the API token and mesh secret — owner-only from creation.
  ( umask 177 && cp deploy/aeon.env.example "$DATA_DIR/aeon.env" )
  chmod 600 "$DATA_DIR/aeon.env"
  echo "    wrote $DATA_DIR/aeon.env (600) — EDIT IT (set AEON_API_TOKEN, paths)."
fi

echo "==> Web app build"
if command -v npm >/dev/null 2>&1; then
  ( cd web && npm install --silent && npm run build )
else
  echo "    npm not found — skipping web build (API-only until you build web/)."
fi

echo "==> systemd user services"
mkdir -p "$SYSTEMD_DIR"
cp deploy/aeon-server.service deploy/aeon-mesh-peer.service "$SYSTEMD_DIR/"
systemctl --user daemon-reload
loginctl enable-linger "$USER" >/dev/null 2>&1 || true

cat <<EOF

==> Done. Next:
    1. Edit $DATA_DIR/aeon.env (token, models, mesh).
    2. systemctl --user enable --now aeon-server
    3. (optional) systemctl --user enable --now aeon-mesh-peer
    4. Open http://<this-host>:8900 and paste your token in Settings.
EOF
