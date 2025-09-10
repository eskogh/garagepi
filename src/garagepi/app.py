import os
import time
import threading
import signal
import atexit

from flask import Flask, jsonify, render_template, request, abort
from .gpio import setup_default, GPIO  # import GPIO for cleanup
from . import mqtt as hamq

# --- Pins / timings ---
PIN_TRIGGER = int(os.getenv("PIN_TRIGGER", "4"))
PIN_SENSOR_OPEN = int(os.getenv("PIN_SENSOR_OPEN", "14"))
PIN_SENSOR_CLOSED = int(os.getenv("PIN_SENSOR_CLOSED", "16"))
TRIGGER_PULSE_S = float(os.getenv("TRIGGER_PULSE_S", "0.5"))
MIN_TOGGLE_GAP_S = float(os.getenv("MIN_TOGGLE_GAP_S", "2.0"))

# --- API auth (optional) ---
API_TOKEN = os.getenv("API_TOKEN", "").strip()

# --- MQTT / HA ---
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "garagepi")
DISCOVERY_PREFIX = os.getenv("DISCOVERY_PREFIX", "homeassistant")
NODE_ID = os.getenv("NODE_ID", "garagepi")
BASE = os.getenv("MQTT_BASE", "garagepi")

TOPIC_AVAIL = f"{BASE}/availability"
TOPIC_COVER_SET = f"{BASE}/cover/set"
TOPIC_COVER_STATE = f"{BASE}/cover/state"
TOPIC_CM_SET = f"{BASE}/close_mode/set"
TOPIC_CM_STATE = f"{BASE}/close_mode/state"

GPIO, ON_PI = setup_default(PIN_TRIGGER, PIN_SENSOR_OPEN, PIN_SENSOR_CLOSED)
app = Flask(__name__, template_folder="templates")

close_mode = False
last_toggle = 0.0
_last_published_state = None
_mq = None  # paho client


# --- helpers ---
def _require_token() -> None:
    """Enforce Bearer token for mutating endpoints if API_TOKEN is set."""
    if not API_TOKEN:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        abort(401, "Missing bearer token")
    supplied = auth.split(" ", 1)[1].strip()
    if supplied != API_TOKEN:
        abort(401, "Invalid token")


def check_door_status() -> str:
    is_open = GPIO.input(PIN_SENSOR_OPEN) == 1
    is_closed = GPIO.input(PIN_SENSOR_CLOSED) == 1
    if is_open and not is_closed:
        return "Open"
    if is_closed and not is_open:
        return "Closed"
    if not is_open and not is_closed:
        return "Moving"
    return "Unknown"


def pulse_trigger() -> None:
    GPIO.output(PIN_TRIGGER, 1)
    time.sleep(TRIGGER_PULSE_S)
    GPIO.output(PIN_TRIGGER, 0)


def _publish_availability(state: str) -> None:
    if _mq:
        _mq.publish(TOPIC_AVAIL, state, qos=1, retain=True)


def _publish_state_if_changed(force: bool = False) -> None:
    global _last_published_state
    state = check_door_status().lower()
    if force or state != _last_published_state:
        _last_published_state = state
        if _mq:
            _mq.publish(TOPIC_COVER_STATE, state, qos=1, retain=True)


def _publish_close_mode() -> None:
    if _mq:
        _mq.publish(TOPIC_CM_STATE, "ON" if close_mode else "OFF", qos=1, retain=True)


def _handle_cover_command(payload: str) -> None:
    # Many motors are toggle-only; map OPEN/CLOSE/STOP to one pulse.
    if close_mode and payload.upper() in ("OPEN", "CLOSE"):
        return
    _rate_limit()
    pulse_trigger()


def _handle_cm_command(payload: str) -> None:
    global close_mode
    p = payload.strip().upper()
    if p == "ON":
        close_mode = True
    elif p == "OFF":
        close_mode = False
    _publish_close_mode()


def _rate_limit() -> None:
    global last_toggle
    now = time.time()
    if now - last_toggle < MIN_TOGGLE_GAP_S:
        return
    last_toggle = now


# --- MQTT setup ---
def _mqtt_start() -> None:
    global _mq
    _mq = hamq.connect(
        client_id=MQTT_CLIENT_ID,
        host=MQTT_HOST,
        port=MQTT_PORT,
        user=MQTT_USER,
        password=MQTT_PASSWORD,
    )
    if not _mq:
        print("MQTT not available; continuing without broker.")
        return

    def on_connect(client, userdata, flags, reason_code, properties=None):
        try:
            hamq.publish_discovery(
                client,
                DISCOVERY_PREFIX,
                NODE_ID,
                TOPIC_AVAIL,
                TOPIC_COVER_STATE,
                TOPIC_COVER_SET,
                TOPIC_CM_STATE,
                TOPIC_CM_SET,
            )
            client.subscribe(TOPIC_COVER_SET, qos=1)
            client.subscribe(TOPIC_CM_SET, qos=1)
            _publish_availability("online")
            _publish_state_if_changed(force=True)
            _publish_close_mode()
        except Exception as e:  # noqa: BLE001
            print("MQTT connect handling failed:", e)

    def on_message(client, userdata, msg):
        try:
            payload = (msg.payload or b"").decode().strip()
            if msg.topic == TOPIC_COVER_SET:
                _handle_cover_command(payload)
            elif msg.topic == TOPIC_CM_SET:
                _handle_cm_command(payload)
        except Exception as e:  # noqa: BLE001
            print("MQTT message error:", e)

    _mq.on_connect = on_connect
    _mq.on_message = on_message


def _mqtt_stop() -> None:
    try:
        _publish_availability("offline")
    except Exception:
        pass
    try:
        if _mq:
            _mq.loop_stop()
    except Exception:
        pass


# --- Background loops ---
def enforce_close_loop() -> None:
    while True:
        try:
            if close_mode and check_door_status() == "Open":
                _rate_limit()
                pulse_trigger()
        except Exception as e:  # noqa: BLE001
            print("enforce_close_loop error:", e)
        time.sleep(5)


def state_publish_loop() -> None:
    while True:
        try:
            _publish_state_if_changed()
        except Exception as e:  # noqa: BLE001
            print("state_publish_loop error:", e)
        time.sleep(1.0)


# --- Flask routes ---
@app.route("/")
def index():
    return render_template("index.html", door_status=check_door_status(), close_mode=close_mode)


@app.route("/status")
def status():
    return jsonify({"status": check_door_status(), "close_mode": close_mode})


@app.route("/toggle", methods=["POST"])
def toggle():
    _require_token()
    if close_mode:
        abort(403, "Close Mode is enabled")
    _rate_limit()
    pulse_trigger()
    return jsonify({"status": "Toggled"})


@app.route("/set_close_mode", methods=["POST"])
def set_close_mode():
    _require_token()
    global close_mode
    data = request.get_json(force=True)
    close_mode = bool(data.get("enabled"))
    _publish_close_mode()
    return jsonify({"close_mode": close_mode})


def create_app():
    return app


# --- startup/shutdown ---
def _start_threads() -> None:
    threading.Thread(target=enforce_close_loop, daemon=True).start()
    threading.Thread(target=state_publish_loop, daemon=True).start()


def _on_exit(*_):
    try:
        _mqtt_stop()
    except Exception:
        pass
    try:
        GPIO.cleanup()
    except Exception:
        pass


atexit.register(_on_exit)
signal.signal(signal.SIGTERM, _on_exit)
signal.signal(signal.SIGINT, _on_exit)

_mqtt_start()
_publish_availability("online")
_start_threads()
