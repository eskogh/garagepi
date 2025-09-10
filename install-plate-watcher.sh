#!/usr/bin/env bash
set -euo pipefail

# ---------- pretty logging ----------
c_reset="\033[0m"; c_red="\033[31m"; c_green="\033[32m"; c_yel="\033[33m"; c_cyan="\033[36m"
log()   { echo -e "${c_cyan}▶${c_reset} $*"; }
ok()    { echo -e "${c_green}✅${c_reset} $*"; }
warn()  { echo -e "${c_yel}⚠️ ${c_reset} $*"; }
err()   { echo -e "${c_red}❌${c_reset} $*" >&2; }

# ---------- root check ----------
if [[ $EUID -ne 0 ]]; then
  err "This installer must be run as root (use sudo)."
  exit 1
fi

# ---------- helpers ----------
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Required command not found: $1"; exit 1; }
}

prompt() {
  local text="$1"; local def="${2:-}"; local val=""
  if [[ -n "$def" ]]; then
    read -rp "$text [$def]: " val
    printf "%s" "${val:-$def}"
  else
    read -rp "$text: " val
    printf "%s" "${val}"
  fi
}

safe_write() {
  # safe_write <dest> <<EOF ... EOF
  local dest="$1"
  local tmp
  tmp="$(mktemp "${dest}.XXXXXX")"
  cat >"$tmp"
  mv -f "$tmp" "$dest"
}

# ---------- paths & checks ----------
SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="${SCRIPT_DIR}"

UNIT_NAME="plate_watcher.service"
UNIT_DST="/etc/systemd/system/${UNIT_NAME}"
ENV_FILE="/etc/default/plate_watcher"

require_cmd python3
require_cmd systemctl
require_cmd journalctl

PY_BIN="$(command -v python3)"
WATCHER_PATH="${REPO_ROOT}/automation/plate_watcher.py"
if [[ ! -f "${WATCHER_PATH}" ]]; then
  err "Not found: ${WATCHER_PATH}  (expected inside repo automation/)"
  exit 1
fi

# Optional, but often needed for RTSP/frames
if ! command -v ffmpeg >/dev/null 2>&1; then
  warn "ffmpeg not found. RTSP frame grabbing may fail. Install with: sudo apt-get install -y ffmpeg"
fi
if ! command -v curl >/dev/null 2>&1; then
  warn "curl not found. HTTP calls to GaragePi may fail. Install with: sudo apt-get install -y curl"
fi

# ---------- interactive config ----------
echo "=== Plate Watcher Setup ==="
RTSP_URL=$(prompt "RTSP URL (rtsp://user:pass@IP:554/path)")
PLATE_API_TOKEN=$(prompt "Plate Recognizer API token (leave blank to fill later)" "")
APPROVED_PLATES=$(prompt "Approved plates (comma-separated, e.g. ABC123,XYZ987)")
MIN_SCORE=$(prompt "Minimum plate score (0-1)" "0.85")
SAMPLE_SECS=$(prompt "Sampling interval (seconds)" "1.5")
OPEN_COOLDOWN_S=$(prompt "Cooldown after open (seconds)" "30")

echo
echo "GaragePi API settings (used to trigger the door via HTTP):"
GARAGEPI_URL=$(prompt "GaragePi base URL" "http://127.0.0.1:5000")
GARAGEPI_TOKEN=$(prompt "GaragePi API token (must match API_TOKEN in garagepi)" "changeme")

# basic sanity
[[ -z "$RTSP_URL" ]] && { err "RTSP_URL cannot be empty."; exit 1; }

# ---------- write unit ----------
log "Writing systemd unit → ${UNIT_DST}"
safe_write "${UNIT_DST}" <<EOF || { err "Failed to write unit file"; exit 1; }
[Unit]
Description=GaragePi Plate Watcher (RTSP -> ALPR -> Garage)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=${REPO_ROOT}
EnvironmentFile=${ENV_FILE}
ExecStart=${PY_BIN} ${WATCHER_PATH}
Restart=always
RestartSec=5

# Hardening
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# ---------- write env file ----------
log "Writing environment file → ${ENV_FILE}"
safe_write "${ENV_FILE}" <<EOF || { err "Failed to write env file"; exit 1; }
# ==== Plate Watcher Environment ====
# Camera
RTSP_URL=${RTSP_URL}

# Plate Recognizer API
PLATE_API_TOKEN=${PLATE_API_TOKEN}
MIN_SCORE=${MIN_SCORE}
SAMPLE_SECS=${SAMPLE_SECS}
OPEN_COOLDOWN_S=${OPEN_COOLDOWN_S}

# Whitelist (comma separated, case-insensitive)
APPROVED_PLATES=${APPROVED_PLATES}

# GaragePi HTTP control
GARAGEPI_URL=${GARAGEPI_URL}
GARAGEPI_TOKEN=${GARAGEPI_TOKEN}
EOF

# tighten perms on env (may contain secrets)
chmod 600 "${ENV_FILE}" || { err "Failed to chmod 600 ${ENV_FILE}"; exit 1; }
chown root:root "${ENV_FILE}" || { err "Failed to chown root:root ${ENV_FILE}"; exit 1; }

# ---------- enable & start ----------
log "Reloading systemd"
systemctl daemon-reload || { err "systemctl daemon-reload failed"; exit 1; }

log "Enabling ${UNIT_NAME}"
systemctl enable "${UNIT_NAME}" || { err "Failed to enable ${UNIT_NAME}"; exit 1; }

log "Starting ${UNIT_NAME}"
if ! systemctl start "${UNIT_NAME}"; then
  err "Failed to start ${UNIT_NAME}"
  journalctl -u "${UNIT_NAME}" -n 50 --no-pager || true
  exit 1
fi

# verify active
if systemctl is-active --quiet "${UNIT_NAME}"; then
  ok "Plate watcher is active."
else
  err "Service is not active after start."
  journalctl -u "${UNIT_NAME}" -n 50 --no-pager || true
  exit 1
fi

ok "Installed successfully."
echo "Logs:  journalctl -u ${UNIT_NAME} -f"
echo "Config: ${ENV_FILE} (edit then: systemctl restart ${UNIT_NAME})"
