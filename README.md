# GaragePi – Flask + GPIO + MQTT (Home Assistant Discovery)

A tiny Flask app to control a garage door relay on Raspberry Pi GPIO, with:
- Debounced sensor reads + edge callbacks
- “Close Mode” (auto-close enforcement)
- Secure API (optional bearer token)
- **MQTT Discovery** for Home Assistant (Cover + Switch)
- Neon-styled single-page UI
- Optional **Plate Watcher** integration for automatic opening via license plate recognition

---

## Hardware

- **PIN_TRIGGER**: relay/optocoupler to the motor controller push-button input
- **PIN_SENSOR_OPEN**: magnetic/reed or limit switch for *open*
- **PIN_SENSOR_CLOSED**: magnetic/reed or limit switch for *closed*
Pull-downs assumed; invert in code if your wiring differs.

---

## Install

```bash
sudo apt update
sudo apt install -y python3-pip
pip install -e .
```

---

## Configure

Set environment variables (create a `.env` or export in your service):

```bash
# Flask
HOST=0.0.0.0
PORT=5000
API_TOKEN=changeme  # optional

# GPIO pins (BCM)
PIN_TRIGGER=4
PIN_SENSOR_OPEN=14
PIN_SENSOR_CLOSED=16

# Behavior
TRIGGER_PULSE_S=0.5
MIN_TOGGLE_GAP_S=2.0

# MQTT / HA
MQTT_HOST=192.168.1.10
MQTT_PORT=1883
MQTT_USER=ha
MQTT_PASSWORD=yourpass
MQTT_CLIENT_ID=garagepi
DISCOVERY_PREFIX=homeassistant
NODE_ID=garagepi
MQTT_BASE=garagepi
```

---

## Run

Install and run via the CLI entry point:

```bash
garagepi
```

Or via Python module:

```bash
python -m garagepi
```

---

## systemd service (recommended)

Use the provided interactive installer:

```bash
sudo ./install-service.sh
```

This will:
- Prompt for configuration (pins, MQTT, etc.)
- Write `/etc/default/garagepi`
- Install and enable `garagepi.service`

Check status with:

```bash
systemctl status garagepi
journalctl -u garagepi -f
```

---

## Home Assistant

- Uses **MQTT Discovery** (best protocol for this use case).
- After the app connects to your broker, HA will auto-add:
  - **Cover**: *Garage Door* (`cover.garage_door`)
  - **Switch**: *Garage Close Mode* (`switch.garage_close_mode`)

### Topics (defaults)
- Availability: `garagepi/availability` → `online` / `offline`
- Cover command: `garagepi/cover/set` → `OPEN` / `CLOSE` / `STOP`
- Cover state: `garagepi/cover/state` → `open` / `closed` / `opening` / `closing` / `unknown`
- Close mode set: `garagepi/close_mode/set` → `ON` / `OFF`
- Close mode state: `garagepi/close_mode/state` → `ON` / `OFF`

> Note: Many garage motors use a *toggle* input; all cover commands map to a single relay pulse. State correctness comes from your sensors.

---

## Security

- Use `API_TOKEN` to require `Authorization: Bearer <token>` for `/toggle` and `/set_close_mode`.
- Keep your MQTT broker LAN-restricted and use credentials.

---

## Development

- On non-Pi machines the app uses a **GPIO shim** so you can develop the Flask/MQTT logic without hardware.

Run linting and tests:

```bash
make lint
make test
```

---

## Plate Watcher (optional)

A companion service that watches your RTSP/ONVIF camera and triggers GaragePi if your car’s plate is detected using the Plate Recognizer API.

### Install

```bash
sudo ./install-plate-watcher.sh
```

This will:
- Prompt for RTSP URL, approved plates, Plate Recognizer API token, and GaragePi settings
- Write `/etc/default/plate_watcher`
- Install and enable `plate_watcher.service`

Logs:

```bash
journalctl -u plate_watcher -f
```

---

## Troubleshooting

- **No entities appear in HA**: check MQTT Discovery prefix (`homeassistant`) and that HA is connected to the same broker. Verify topics with `mosquitto_sub -t 'homeassistant/#'`.
- **State wrong**: invert your sensor wiring or adjust logic in `_read_state()`.
- **Spam or double toggles**: increase `MIN_TOGGLE_GAP_S`.

---

## License

MIT License – see [LICENSE](LICENSE).
