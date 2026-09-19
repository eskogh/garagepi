import os
import time
import threading
import signal
import atexit
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, TypedDict

from flask import Flask, Response, abort, jsonify, render_template, request

from .gpio import setup_default
from . import mqtt as hamq

log = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


service_started_at = _utc_now_iso()


def _optional_pin(name: str, default: str = "") -> Optional[int]:
    raw = os.getenv(name, default).strip()
    if not raw or raw.lower() in {"none", "off", "disabled"}:
        return None
    return int(raw)


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
    sensor_open: str
    sensor_closed: str

    @classmethod
    def from_base(cls, base: str) -> "Topics":
        return cls(
            availability=f"{base}/availability",
            cover_set=f"{base}/cover/set",
            cover_state=f"{base}/cover/state",
            close_mode_set=f"{base}/close_mode/set",
            close_mode_state=f"{base}/close_mode/state",
            sensor_open=f"{base}/sensor/open",
            sensor_closed=f"{base}/sensor/closed",
        )


@dataclass(frozen=True)
class Config:
    trigger_pin: int
    sensor_open_pin: Optional[int]
    sensor_closed_pin: Optional[int]
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
    camera_url: str

    @property
    def topics(self) -> Topics:
        return Topics.from_base(self.mqtt_base)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            trigger_pin=int(os.getenv("PIN_TRIGGER", "4")),
            sensor_open_pin=_optional_pin("PIN_SENSOR_OPEN", "15"),
            sensor_closed_pin=_optional_pin("PIN_SENSOR_CLOSED", "14"),
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
            camera_url=os.getenv(
                "CAMERA_URL",
                "http://10.13.37.233:1984/api/stream.m3u8?src=cam7",
            ).strip(),
        )


config = Config.from_env()
GPIO, ON_PI = setup_default(
    config.trigger_pin,
    config.sensor_open_pin,
    config.sensor_closed_pin,
)


class SensorSnapshot(TypedDict):
    name: str
    pin: Optional[int]
    raw: Optional[int]
    mode: str
    active: bool
    readable: bool
    connected: bool
    last_changed: Optional[str]
    last_read: Optional[str]
    error: str


def _empty_sensor(name: str, pin: Optional[int]) -> SensorSnapshot:
    return {
        "name": name,
        "pin": pin,
        "raw": None,
        "mode": "disabled" if pin is None else "unknown",
        "active": False,
        "readable": False,
        "connected": False,
        "last_changed": None,
        "last_read": None,
        "error": "",
    }


sensor_snapshots = {
    "open": _empty_sensor("Open sensor", config.sensor_open_pin),
    "closed": _empty_sensor("Closed sensor", config.sensor_closed_pin),
}
last_motor_triggered_at: Optional[str] = None


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
_shutdown_done = False
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
    sensors = read_sensor_snapshots()
    configured = [sensor for sensor in sensors.values() if sensor["pin"] is not None]
    if not configured:
        return DoorState.UNKNOWN
    if len(configured) == 1:
        return DoorState.CLOSED if configured[0]["active"] else DoorState.OPEN

    is_open = sensors["open"]["active"]
    is_closed = sensors["closed"]["active"]
    if is_open and not is_closed:
        return DoorState.OPEN
    if is_closed and not is_open:
        return DoorState.CLOSED
    if not is_open and not is_closed:
        return DoorState.MOVING
    return DoorState.UNKNOWN


def check_door_status() -> str:
    return get_door_state().label


def sensor_config_mode() -> str:
    configured = [
        pin
        for pin in (config.sensor_open_pin, config.sensor_closed_pin)
        if pin is not None
    ]
    if not configured:
        return "none"
    if len(configured) == 1:
        return "single"
    return "dual"


def pulse_trigger() -> None:
    global last_motor_triggered_at
    last_motor_triggered_at = _utc_now_iso()
    GPIO.output(config.trigger_pin, 1)
    time.sleep(config.trigger_pulse_s)
    GPIO.output(config.trigger_pin, 0)


def _update_sensor_snapshot(key: str, name: str, pin: Optional[int]) -> SensorSnapshot:
    now = _utc_now_iso()
    previous = sensor_snapshots[key]
    if pin is None:
        snapshot: SensorSnapshot = {
            **previous,
            "name": name,
            "pin": None,
            "raw": None,
            "mode": "disabled",
            "active": False,
            "readable": False,
            "connected": False,
            "last_read": None,
            "error": "",
        }
        sensor_snapshots[key] = snapshot
        return snapshot

    try:
        raw = int(GPIO.input(pin))
    except Exception as exc:  # noqa: BLE001
        snapshot: SensorSnapshot = {
            **previous,
            "name": name,
            "pin": pin,
            "raw": None,
            "mode": "read error",
            "active": False,
            "readable": False,
            "connected": False,
            "last_read": now,
            "error": f"{type(exc).__name__}: {exc}",
        }
        if previous["readable"]:
            snapshot["last_changed"] = now
        sensor_snapshots[key] = snapshot
        return snapshot

    active = raw == 0
    mode = "active" if active else "inactive"
    changed = (
        previous["raw"] is None
        or previous["raw"] != raw
        or not previous["readable"]
    )
    snapshot = {
        "name": name,
        "pin": pin,
        "raw": raw,
        "mode": mode,
        "active": active,
        "readable": True,
        "connected": True,
        "last_changed": now if changed else previous["last_changed"],
        "last_read": now,
        "error": "",
    }
    sensor_snapshots[key] = snapshot
    return snapshot


def read_sensor_snapshots() -> dict[str, SensorSnapshot]:
    return {
        "open": _update_sensor_snapshot(
            "open",
            "Open sensor",
            config.sensor_open_pin,
        ),
        "closed": _update_sensor_snapshot(
            "closed",
            "Closed sensor",
            config.sensor_closed_pin,
        ),
    }


def diagnostics() -> dict:
    sensors = read_sensor_snapshots()
    configured = [sensor for sensor in sensors.values() if sensor["pin"] is not None]
    both_active = (
        len(configured) == 2
        and sensors["open"]["active"]
        and sensors["closed"]["active"]
    )
    all_readable = all(sensor["readable"] for sensor in configured)
    sensor_mode = (
        "none" if not configured else "single" if len(configured) == 1 else "dual"
    )
    return {
        "service_started_at": service_started_at,
        "sensor_mode": sensor_mode,
        "sensors": sensors,
        "sensor_health": (
            "disabled"
            if not configured
            else "conflict"
            if both_active
            else "ok"
            if all_readable
            else "read_error"
        ),
        "sensor_note": (
            "No sensors configured; the button only sends a motor trigger."
            if not configured
            else "One-sensor mode: active means closed, inactive means open."
            if len(configured) == 1 and all_readable
            else "Both sensors are active; check wiring or sensor positions."
            if both_active
            else (
                "GPIO reads are working. Last-change times are observed since "
                "service start; simple pull-down sensors cannot prove wire continuity."
            )
            if all_readable
            else "At least one GPIO read failed."
        ),
        "motor": {
            "trigger_pin": config.trigger_pin,
            "last_triggered_at": last_motor_triggered_at,
        },
    }


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
    if command not in {"OPEN", "CLOSE", "STOP"}:
        return

    if sensor_config_mode() == "none":
        if command == "OPEN" and close_mode:
            return
        _pulse_if_allowed()
        return

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

def _publish_sensor_states() -> None:
    if not _mq:
        return

    sensors = read_sensor_snapshots()

    if config.sensor_open_pin is not None:
        _mq.publish(
            config.topics.sensor_open,
            "ON" if sensors["open"]["active"] else "OFF",
            qos=1,
            retain=True,
        )

    if config.sensor_closed_pin is not None:
        _mq.publish(
            config.topics.sensor_closed,
            "ON" if sensors["closed"]["active"] else "OFF",
            qos=1,
            retain=True,
        )

# --- MQTT setup ---
def _mqtt_start() -> None:
    global _mq

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            log.warning(
                "MQTT connection refused by %s:%s for client_id=%r: %s",
                config.mqtt_host,
                config.mqtt_port,
                config.mqtt_client_id,
                reason_code,
            )
            return

        log.info(
            "MQTT connected to %s:%s as client_id=%r",
            config.mqtt_host,
            config.mqtt_port,
            config.mqtt_client_id,
        )

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
                config.topics.sensor_open,
                config.topics.sensor_closed,
            )

            client.subscribe(config.topics.cover_set, qos=1)
            client.subscribe(config.topics.close_mode_set, qos=1)

            _publish_availability("online")
            _publish_state_if_changed(force=True)
            _publish_sensor_states()
            _publish_close_mode()

        except Exception as e:  # noqa: BLE001
            log.exception("MQTT connect handling failed: %s", e)
            
            
    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
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
        log.warning(
            "MQTT not available at %s:%s for client_id=%r: %s: %s",
            config.mqtt_host,
            config.mqtt_port,
            config.mqtt_client_id,
            type(e).__name__,
            e,
        )
        _mq = None
        return

    if _mq is None:
        log.warning(
            "MQTT client unavailable for %s:%s with client_id=%r",
            config.mqtt_host,
            config.mqtt_port,
            config.mqtt_client_id,
        )
        return

    log.info(
        "MQTT client started for %s:%s with client_id=%r; waiting for CONNACK",
        config.mqtt_host,
        config.mqtt_port,
        config.mqtt_client_id,
    )


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
        sensor_mode=sensor_config_mode(),
        close_mode=close_mode,
        api_token_required=bool(config.api_token),
        camera_url=config.camera_url,
    )


@app.route("/status")
def status() -> Response:
    return jsonify(
        {
            "status": check_door_status(),
            "close_mode": close_mode,
            "diagnostics": diagnostics(),
        }
    )


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
    global _shutdown_done
    if _shutdown_done:
        return
    _shutdown_done = True
    try:
        _mqtt_stop()
    except Exception:
        pass
    try:
        GPIO.cleanup()
    except Exception:
        pass


def _on_signal(signum, frame) -> None:
    _on_exit(signum, frame)
    raise SystemExit(0)


atexit.register(_on_exit)
signal.signal(signal.SIGTERM, _on_signal)
signal.signal(signal.SIGINT, _on_signal)
