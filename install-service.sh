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
  local dest="$1"
  local tmp
  tmp="$(mktemp "${dest}.XXXXXX")"
  cat >"$tmp"
  mv -f "$tmp" "$dest"
}

# ---------- paths & checks ----------
require_cmd python3
require_cmd systemctl
require_cmd journalctl

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="${SCRIPT_DIR}"

UNIT_NAME="garagepi.service"
UNIT_DST="/etc/systemd/system/${UNIT_NAME}"
ENV_FILE="/etc/default/garagepi"

# Prefer installed console entrypoint; fall back to module
if command -v garagepi >/dev/null 2>&1; then
  EXEC_CMD="$(command -v garagepi)"
else
  EXEC_CMD="$(command -v python3) -m garagepi"
  warn "console script 'garagepi' not found; will run '${EXEC_CMD}'. Ensure the package is installed (e.g. 'pip install -e .')."
fi

# ---------- interactive config ----------
echo "=== GaragePi Setup ==="
HOST=$(prompt "Host to bind Flask" "0.0.0.0")
PORT=$(prompt "Port for Flask" "5000")
API_TOKEN=$(prompt "API token for securing /toggle and /set_close_mode" "changeme")

PIN_TRIGGER=$(prompt "BCM pin for relay trigger (PIN_TRIGGER)" "4")
PIN_SENSOR_OPEN=$(prompt "BCM pin for OPEN sensor (PIN_SENSOR_OPEN)" "14")
PIN_SENSOR_CLOSED=$(prompt "BCM pin for CLOSED sensor (PIN_SENSOR_CLOSED)" "16")

TRIGGER_PULSE_S=$(prompt "Relay pulse length (seconds) (TRIGGER_PULSE_S)" "0.5")
MIN_TOGGLE_GAP_S=$(prompt "Minimum toggle gap (seconds) (MIN_TOGGLE_GAP_S)" "2.0")

MQTT_HOST=$(prompt "MQTT broker host" "127.0.0.1")
MQTT_PORT=$(prompt "MQTT broker port" "1883")
MQTT_USER=$(prompt "MQTT username" "")
MQTT_PASSWORD=$(prompt "MQTT password" "")
MQTT_CLIENT_ID=$(prompt "MQTT client ID" "garagepi")
DISCOVERY_PREFIX=$(prompt "MQTT discovery prefix" "homeassistant")
NODE_ID=$(prompt "Home Assistant node ID" "garagepi")
MQTT_BASE=$(prompt "MQTT base topic" "garagepi")

# ---------- write unit ----------
log "Writing systemd unit → ${UNIT_DST}"
safe_write "${UNIT_DST}" <<EOF || { err "Failed to write unit file"; exit 1; }
[Unit]
Description=GaragePi – Raspberry Pi Garage Door Controller
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=${REPO_ROOT}
EnvironmentFile=${ENV_FILE}
ExecStart=${EXEC_CMD}
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

# ---------- write env ----------
log "Writing environment file → ${ENV_FILE}"
safe_write "${ENV_FILE}" <<EOF || { err "Failed to write env file"; exit 1; }
# ==== GaragePi Environment ====
# Flask
HOST=${HOST}
PORT=${PORT}
API_TOKEN=${API_TOKEN}

# GPIO pins (BCM)
PIN_TRIGGER=${PIN_TRIGGER}
PIN_SENSOR_OPEN=${PIN_SENSOR_OPEN}
PIN_SENSOR_CLOSED=${PIN_SENSOR_CLOSED}

# Behavior
TRIGGER_PULSE_S=${TRIGGER_PULSE_S}
MIN_TOGGLE_GAP_S=${MIN_TOGGLE_GAP_S}

# MQTT / Home Assistant
MQTT_HOST=${MQTT_HOST}
MQTT_PORT=${MQTT_PORT}
MQTT_USER=${MQTT_USER}
MQTT_PASSWORD=${MQTT_PASSWORD}
MQTT_CLIENT_ID=${MQTT_CLIENT_ID}
DISCOVERY_PREFIX=${DISCOVERY_PREFIX}
NODE_ID=${NODE_ID}
MQTT_BASE=${MQTT_BASE}
EOF

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

if systemctl is-active --quiet "${UNIT_NAME}"; then
  ok "GaragePi is active."
else
  err "Service is not active after start."
  journalctl -u "${UNIT_NAME}" -n 50 --no-pager || true
  exit 1
fi

ok "Installed successfully."
echo "Logs:  journalctl -u ${UNIT_NAME} -f"
echo "Config: ${ENV_FILE} (edit then: systemctl restart ${UNIT_NAME})"
