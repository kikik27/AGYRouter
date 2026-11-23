#!/usr/bin/env bash
set -euo pipefail

MODE="user"
if [[ "${1:-}" == "--system" ]]; then
    MODE="system"
elif [[ "${1:-}" == "--user" || -z "${1:-}" ]]; then
    MODE="user"
else
    echo "Usage: $0 [--user | --system]"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SERVICE_NAME="agy-router"

echo "========================================================"
echo "  AGY Router - Linux systemd Installer ($MODE mode)"
echo "========================================================"
echo "Repo dir: $REPO_DIR"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 tidak ditemukan. Install Python 3.10+ terlebih dahulu."
    exit 1
fi

if [[ ! -d "$REPO_DIR/.venv" ]]; then
    echo "Membuat Python virtual environment (.venv)..."
    python3 -m venv "$REPO_DIR/.venv"
fi

echo "Menginstall dependensi Python..."
"$REPO_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"

if [[ ! -f "$REPO_DIR/.env" && -f "$REPO_DIR/.env.example" ]]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
fi

VENV_PYTHON="$REPO_DIR/.venv/bin/python"
AGY_BIN_DIR=""
if command -v agy >/dev/null 2>&1; then
    AGY_BIN_DIR="$(dirname "$(command -v agy)")"
fi
UNIT_PATH="$REPO_DIR/.venv/bin:${AGY_BIN_DIR:+$AGY_BIN_DIR:}/usr/local/bin:/usr/bin:/bin"

if [[ "$MODE" == "user" ]]; then
    UNIT_DIR="${HOME}/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    UNIT_FILE="$UNIT_DIR/${SERVICE_NAME}.service"

    cat > "$UNIT_FILE" <<EOF
[Unit]
Description=AGY Router - Official Local AI Gateway (by kikik27)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
Environment="HOME=$HOME"
Environment="PATH=$UNIT_PATH"
ExecStart=$VENV_PYTHON $REPO_DIR/run.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable --now "${SERVICE_NAME}"

    if command -v loginctl >/dev/null 2>&1; then
        loginctl enable-linger "$USER" 2>/dev/null || true
    fi

    echo ""
    echo "[OK] Service user '${SERVICE_NAME}' aktif dan autostart!"
    echo "Cek status : systemctl --user status ${SERVICE_NAME}"
    echo "Lihat log  : journalctl --user -u ${SERVICE_NAME} -f"
else
    TARGET_USER="${SUDO_USER:-$USER}"
    TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
    if [[ -z "$TARGET_HOME" ]]; then
        TARGET_HOME="/home/$TARGET_USER"
    fi
    UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    TMP_FILE="$(mktemp)"
    cat > "$TMP_FILE" <<EOF
[Unit]
Description=AGY Router - Official Local AI Gateway (by kikik27)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${TARGET_USER}
WorkingDirectory=$REPO_DIR
Environment="HOME=${TARGET_HOME}"
Environment="PATH=$UNIT_PATH"
ExecStart=$VENV_PYTHON $REPO_DIR/run.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    sudo cp "$TMP_FILE" "$UNIT_FILE"
    rm -f "$TMP_FILE"
    sudo systemctl daemon-reload
    sudo systemctl enable --now "${SERVICE_NAME}"

    echo ""
    echo "[OK] System service '${SERVICE_NAME}' aktif dan autostart!"
    echo "Cek status : sudo systemctl status ${SERVICE_NAME}"
    echo "Lihat log  : sudo journalctl -u ${SERVICE_NAME} -f"
fi
