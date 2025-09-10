# GaragePi – Flask + GPIO + MQTT (Home Assistant Discovery)

A tiny Flask app to control a garage door relay on Raspberry Pi GPIO, with:
- debounced sensor reads + edge callbacks
- “Close Mode” (auto-close enforcement)
- secure API (optional bearer token)
- **MQTT Discovery** for Home Assistant (Cover + Switch)
- neon-styled single-page UI

## Hardware

- **PIN_TRIGGER**: relay/optocoupler to the motor controller push-button input
- **PIN_SENSOR_OPEN**: magnetic/reed or limit switch for *open*
- **PIN_SENSOR_CLOSED**: magnetic/reed or limit switch for *closed*
Pull-downs assumed; invert in code if your wiring differs.

## Install

```bash
sudo apt update
sudo apt install -y python3-pip
pip install -e .
```

## Configure

Set environment variables (create a `.env` or export in your service):

```
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
DEBOUNCE_MS=50
STATUS_CHECK_S=0.25
AUTO_CLOSE_CHECK_S=2.0
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

A helper installer script (`install-server.sh`) is included.  
It will:
- Ensure you run as root
- Prompt for MQTT and API config values
- Write an environment file to `/etc/default/garagepi`
- Copy the unit file to `/etc/systemd/system/garagepi.service`
- Enable and start the service
- Apply basic hardening options

Run it like this:

```bash
sudo ./install-server.sh
```

You can then check logs:

```bash
journalctl -u garagepi -f
```

And edit config at:

```
/etc/default/garagepi
```

Restart the service after config changes:

```bash
sudo systemctl restart garagepi
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

---

## Troubleshooting

- **No entities appear in HA**: check MQTT Discovery prefix (`homeassistant`) and that HA is connected to the same broker. Verify `homeassistant/#` topics show config with `mosquitto_sub`.
- **State wrong**: invert your sensor wiring or adjust the logic in `_read_state()`.
- **Spam or double toggles**: increase `MIN_TOGGLE_GAP_S`.
