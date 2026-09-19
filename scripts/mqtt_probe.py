#!/usr/bin/env python3
import argparse
import os
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / ".vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

import paho.mqtt.client as mqtt


def load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe GaragePi MQTT connectivity.")
    parser.add_argument(
        "--env-file",
        default="",
        help="Optional environment file, for example /etc/default/garagepi.",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    if args.env_file:
        load_env_file(Path(args.env_file))

    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    user = os.getenv("MQTT_USER", "")
    password = os.getenv("MQTT_PASSWORD", "")
    client_id = os.getenv("MQTT_CLIENT_ID", "garagepi-probe")
    topic = f"{os.getenv('MQTT_BASE', 'garagepi')}/probe"

    done = threading.Event()
    result = {"ok": False, "message": "timed out waiting for MQTT CONNACK"}

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            result["message"] = f"broker refused MQTT connection: {reason_code}"
            done.set()
            return
        result["ok"] = True
        result["message"] = "connected and published probe message"
        client.publish(topic, f"garagepi probe {int(time.time())}", qos=1, retain=False)
        done.set()

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
        if not result["ok"] and getattr(reason_code, "is_failure", False):
            result["message"] = f"disconnected before connect completed: {reason_code}"
            done.set()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=True,
    )
    if user:
        client.username_pw_set(user, password or None)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    print(
        f"Probing MQTT {host}:{port} as client_id={client_id!r} "
        f"user_configured={bool(user)} password_configured={bool(password)}"
    )
    try:
        client.connect(host, port, keepalive=30)
    except Exception as exc:  # noqa: BLE001
        print(f"TCP/MQTT connect call failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    client.loop_start()
    done.wait(args.timeout)
    client.loop_stop()
    client.disconnect()

    print(result["message"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
