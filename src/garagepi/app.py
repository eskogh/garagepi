import os
import time
import threading
import signal
import atexit
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from flask import Flask, Response, abort, jsonify, render_template, request
from .gpio import setup_default
from . import mqtt as hamq

log = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """Load simple KEY=VALUE pairs before module-level settings are read."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None

    if load_dotenv:
        load_dotenv(Path.cwd() / ".env")
        load_dotenv(Path(__file__).with_name(".env"))
        return

    candidates = (Path.cwd() / ".env", Path(__file__).with_name(".env"))
    for path in candidates:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key:
                os.environ.setdefault(key, value)


_load_dotenv()


class DoorState(Enum):
    OPEN = "open"
    CLOSED = "closed"
    MOVING = "moving"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return self.value.title()


@dataclass(frozen=True)
class Topics:
    availability: str
    cover_set: str
    cover_state: str
    close_mode_set: str
    close_mode_state: str

    @classmethod
    def from_base(cls, base: str) -> "Topics":
        return cls(
            availability=f"{base}/availability",
            cover_set=f"{base}/cover/set",
            cover_state=f"{base}/cover/state",
            close_mode_set=f"{base}/close_mode/set",
            close_mode_state=f"{base}/close_mode/state",
        )


@dataclass(frozen=True)
class Config:
    trigger_pin: int
    sensor_open_pin: int
    sensor_closed_pin: int
    trigger_pulse_s: float
    min_toggle_gap_s: float
    close_mode_retry_s: float
    api_token: str
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    mqtt_client_id: str
    discovery_prefix: str
    node_id: str
    mqtt_base: str

    @property
    def topics(self) -> Topics:
        return Topics.from_base(self.mqtt_base)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            trigger_pin=int(os.getenv("PIN_TRIGGER", "4")),
            sensor_open_pin=int(os.getenv("PIN_SENSOR_OPEN", "14")),
            sensor_closed_pin=int(os.getenv("PIN_SENSOR_CLOSED", "16")),
            trigger_pulse_s=float(os.getenv("TRIGGER_PULSE_S", "0.5")),
            min_toggle_gap_s=float(os.getenv("MIN_TOGGLE_GAP_S", "2.0")),
            close_mode_retry_s=float(os.getenv("CLOSE_MODE_RETRY_S", "30.0")),
            api_token=os.getenv("API_TOKEN", "").strip(),
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            mqtt_user=os.getenv("MQTT_USER", ""),
            mqtt_password=os.getenv("MQTT_PASSWORD", ""),
            mqtt_client_id=os.getenv("MQTT_CLIENT_ID", "garagepi"),
            discovery_prefix=os.getenv("DISCOVERY_PREFIX", "homeassistant"),
            node_id=os.getenv("NODE_ID", "garagepi"),
            mqtt_base=os.getenv("MQTT_BASE", "garagepi"),
        )


config = Config.from_env()
GPIO, ON_PI = setup_default(
    config.trigger_pin,
    config.sensor_open_pin,
    config.sensor_closed_pin,
)


def _build_app() -> Flask:
    created_app = Flask(__name__, template_folder="templates")
    created_app.config["API_TOKEN_REQUIRED"] = bool(config.api_token)
    return created_app


app = _build_app()

close_mode = False
last_toggle = 0.0
last_close_enforce = 0.0
_last_published_state: Optional[str] = None
_mq = None  # paho client
_runtime_started = False
_runtime_lock = threading.Lock()
_toggle_lock = threading.Lock()


# --- helpers ---
def _require_token() -> None:
    """Enforce Bearer token for mutating endpoints if API_TOKEN is set."""
    if not config.api_token:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        abort(401, "Missing bearer token")
    supplied = auth.split(" ", 1)[1].strip()
    if supplied != config.api_token:
        abort(401, "Invalid token")


def get_door_state() -> DoorState:
    is_open = GPIO.input(config.sensor_open_pin) == 1
    is_closed = GPIO.input(config.sensor_closed_pin) == 1
    if is_open and not is_closed:
        return DoorState.OPEN
    if is_closed and not is_open:
        return DoorState.CLOSED
    if not is_open and not is_closed:
        return DoorState.MOVING
    return DoorState.UNKNOWN


def check_door_status() -> str:
    return get_door_state().label


def pulse_trigger() -> None:
    GPIO.output(config.trigger_pin, 1)
    time.sleep(config.trigger_pulse_s)
    GPIO.output(config.trigger_pin, 0)


def _pulse_if_allowed() -> bool:
    global last_toggle
    with _toggle_lock:
        now = time.time()
        if now - last_toggle < config.min_toggle_gap_s:
            return False
        last_toggle = now
        pulse_trigger()
        return True


def _publish_availability(state: str) -> None:
    if _mq:
        _mq.publish(config.topics.availability, state, qos=1, retain=True)


def _publish_state_if_changed(force: bool = False) -> None:
    global _last_published_state
    state = get_door_state().value
    if force or state != _last_published_state:
        _last_published_state = state
        if _mq:
            _mq.publish(config.topics.cover_state, state, qos=1, retain=True)


def _publish_close_mode() -> None:
    if _mq:
        _mq.publish(
            config.topics.close_mode_state,
            "ON" if close_mode else "OFF",
            qos=1,
            retain=True,
        )


def _handle_cover_command(payload: str) -> None:
    command = payload.strip().upper()
    state = get_door_state()

    if command == "OPEN":
        if close_mode or state is not DoorState.CLOSED:
            return
    elif command == "CLOSE":
        if state is not DoorState.OPEN:
            return
    elif command == "STOP":
        if state is not DoorState.MOVING:
            return
    else:
        return

    _pulse_if_allowed()


def _handle_cm_command(payload: str) -> None:
    global close_mode
    p = payload.strip().upper()
    if p == "ON":
        close_mode = True
    elif p == "OFF":
        close_mode = False
    _publish_close_mode()


# --- MQTT setup ---
def _mqtt_start() -> None:
    global _mq

    def on_connect(client, userdata, flags, reason_code, properties=None):
        try:
            hamq.publish_discovery(
                client,
                config.discovery_prefix,
                config.node_id,
                config.topics.availability,
                config.topics.cover_state,
                config.topics.cover_set,
                config.topics.close_mode_state,
                config.topics.close_mode_set,
            )
            client.subscribe(config.topics.cover_set, qos=1)
            client.subscribe(config.topics.close_mode_set, qos=1)
            _publish_availability("online")
            _publish_state_if_changed(force=True)
            _publish_close_mode()
        except Exception as e:  # noqa: BLE001
            log.exception("MQTT connect handling failed: %s", e)

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
        if reason_code:
            log.warning(
                "MQTT disconnected; reconnect loop will continue: %s",
                reason_code,
            )

    def on_message(client, userdata, msg):
        try:
            payload = (msg.payload or b"").decode().strip()
            if msg.topic == config.topics.cover_set:
                _handle_cover_command(payload)
            elif msg.topic == config.topics.close_mode_set:
                _handle_cm_command(payload)
        except Exception as e:  # noqa: BLE001
            log.exception("MQTT message error: %s", e)

    try:
        _mq = hamq.connect(
            client_id=config.mqtt_client_id,
            host=config.mqtt_host,
            port=config.mqtt_port,
            user=config.mqtt_user,
            password=config.mqtt_password,
            on_connect=on_connect,
            on_disconnect=on_disconnect,
            on_message=on_message,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("MQTT not available; continuing without broker: %s", e)
        _mq = None
        return

    if not _mq:
        log.warning("MQTT not available; continuing without broker.")


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
    global last_close_enforce
    while True:
        try:
            now = time.time()
            if (
                close_mode
                and get_door_state() is DoorState.OPEN
                and now - last_close_enforce >= config.close_mode_retry_s
            ):
                if _pulse_if_allowed():
                    last_close_enforce = now
        except Exception as e:  # noqa: BLE001
            log.exception("enforce_close_loop error: %s", e)
        time.sleep(5)


def state_publish_loop() -> None:
    while True:
        try:
            _publish_state_if_changed()
        except Exception as e:  # noqa: BLE001
            log.exception("state_publish_loop error: %s", e)
        time.sleep(1.0)


# --- Flask routes ---
@app.route("/")
def index() -> str:
    return render_template(
        "index.html",
        door_status=check_door_status(),
        close_mode=close_mode,
        api_token_required=bool(config.api_token),
    )


@app.route("/status")
def status() -> Response:
    return jsonify({"status": check_door_status(), "close_mode": close_mode})


@app.route("/toggle", methods=["POST"])
def toggle() -> Response:
    _require_token()
    if close_mode:
        abort(403, "Close Mode is enabled")
    if not _pulse_if_allowed():
        abort(429, "Too many door operations")
    return jsonify({"status": "Toggled"})


@app.route("/set_close_mode", methods=["POST"])
def set_close_mode() -> Response:
    _require_token()
    global close_mode
    data = request.get_json(force=True)
    close_mode = bool(data.get("enabled"))
    _publish_close_mode()
    return jsonify({"close_mode": close_mode})


def create_app() -> Flask:
    return app


# --- startup/shutdown ---
def _start_threads() -> None:
    threading.Thread(target=enforce_close_loop, daemon=True).start()
    threading.Thread(target=state_publish_loop, daemon=True).start()


def start_runtime() -> None:
    global _runtime_started
    with _runtime_lock:
        if _runtime_started:
            return
        _mqtt_start()
        _start_threads()
        _runtime_started = True


def _on_exit(*_) -> None:
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
