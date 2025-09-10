# GaragePi – Flask + GPIO + MQTT (Home Assistant Discovery)

A tiny Flask app to control a garage door relay on Raspberry Pi GPIO, with:
- debounced sensor reads + edge callbacks
- “Close Mode” (auto-close enforcement)
- **Bearer token** protection for mutating API calls
- **MQTT Discovery** for Home Assistant (Cover + Switch)
- neon-styled single-page UI

## Install

```bash
sudo apt update
sudo apt install -y python3-pip
pip install -e .
```

## Configure (env)

```
# Flask
HOST=0.0.0.0
PORT=5000
API_TOKEN=changeme  # enable token auth for /toggle and /set_close_mode

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

## Run

```bash
garagepi
# or
python -m garagepi
```

Use the token in requests that mutate state:
```bash
curl -X POST http://pi:5000/toggle -H "Authorization: Bearer $API_TOKEN"
curl -X POST http://pi:5000/set_close_mode -H "Authorization: Bearer $API_TOKEN" \
     -H "Content-Type: application/json" -d '{"enabled": true}'
```

### systemd (recommended)

Copy and enable the included service:
```bash
./install-service.sh
```

Optionally place secrets in `/etc/default/garagepi` and add to unit:
```
EnvironmentFile=/etc/default/garagepi
```

## Home Assistant

Auto-discovery via MQTT creates:
- **Cover**: `cover.garage_door`
- **Switch**: `switch.garage_close_mode`

Topics:
- Availability: `<base>/availability` → `online`/`offline`
- Cover command: `<base>/cover/set` (`OPEN`/`CLOSE`/`STOP`)
- Cover state:   `<base>/cover/state` (`open`/`closed`/`opening`/`closing`/`unknown`)
- Close mode set:   `<base>/close_mode/set` (`ON`/`OFF`)
- Close mode state: `<base>/close_mode/state` (`ON`/`OFF`)

## Security Notes

- Keep the web UI on LAN.
- Set a strong `API_TOKEN` and use HTTPS if exposed.
- Keep your MQTT broker credentialed and LAN-only.
