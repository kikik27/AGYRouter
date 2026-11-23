#!/usr/bin/env bash
set -euo pipefail

MODE="user"
if [[ "${1:-}" == "--system" ]]; then
    MODE="system"
fi

SERVICE_NAME="agy-router"

if [[ "$MODE" == "user" ]]; then
    UNIT_FILE="${HOME}/.config/systemd/user/${SERVICE_NAME}.service"
    systemctl --user disable --now "${SERVICE_NAME}" 2>/dev/null || true
    rm -f "$UNIT_FILE"
    systemctl --user daemon-reload
    echo "[OK] User systemd service '${SERVICE_NAME}' dihapus."
else
    UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    sudo systemctl disable --now "${SERVICE_NAME}" 2>/dev/null || true
    sudo rm -f "$UNIT_FILE"
    sudo systemctl daemon-reload
    echo "[OK] System systemd service '${SERVICE_NAME}' dihapus."
fi
