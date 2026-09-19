import json
from typing import Any, Callable, Optional

try:
    import paho.mqtt.client as mqttlib
    MQTT_IMPORT_ERROR = None
except Exception as exc:
    mqttlib = None
    MQTT_IMPORT_ERROR = exc


def connect(
    client_id: str,
    host: str,
    port: int,
    user: str = "",
    password: str = "",
    on_connect: Optional[Callable[..., None]] = None,
    on_disconnect: Optional[Callable[..., None]] = None,
    on_message: Optional[Callable[..., None]] = None,
) -> Any:
    if not mqttlib:
        raise RuntimeError(
            f"paho-mqtt is not importable: {MQTT_IMPORT_ERROR}"
        )

    client = mqttlib.Client(
        callback_api_version=mqttlib.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=True,
    )

    if user:
        client.username_pw_set(user, password or None)

    if on_connect:
        client.on_connect = on_connect

    if on_disconnect:
        client.on_disconnect = on_disconnect

    if on_message:
        client.on_message = on_message

    client.reconnect_delay_set(min_delay=1, max_delay=120)
    client.connect(host, port, keepalive=30)
    client.loop_start()

    return client


def publish_discovery(
    c: Any,
    prefix: str,
    node_id: str,
    avail: str,
    state_topic: str,
    cmd_topic: str,
    cm_state: str,
    cm_set: str,
    sensor_open_topic: str,
    sensor_closed_topic: str,
) -> None:
    if not c:
        return

    device = {
        "identifiers": [node_id],
        "name": "GaragePi",
    }

    #
    # Garage door cover
    #
    cover_cfg_topic = f"{prefix}/cover/{node_id}/cover/config"

    cover_cfg = {
        "name": "Garage Door",
        "unique_id": f"{node_id}_cover",
        "availability_topic": avail,
        "payload_available": "online",
        "payload_not_available": "offline",
        "command_topic": cmd_topic,
        "state_topic": state_topic,
        "payload_open": "OPEN",
        "payload_close": "CLOSE",
        "payload_stop": "STOP",
        "state_open": "open",
        "state_closed": "closed",
        "state_opening": "opening",
        "state_closing": "closing",
        "device": device,
    }

    c.publish(
        cover_cfg_topic,
        json.dumps(cover_cfg),
        qos=1,
        retain=True,
    )

    #
    # Close mode switch
    #
    switch_cfg_topic = f"{prefix}/switch/{node_id}/close_mode/config"

    switch_cfg = {
        "name": "Garage Close Mode",
        "unique_id": f"{node_id}_close_mode",
        "availability_topic": avail,
        "payload_available": "online",
        "payload_not_available": "offline",
        "command_topic": cm_set,
        "state_topic": cm_state,
        "payload_on": "ON",
        "payload_off": "OFF",
        "device": device,
    }

    c.publish(
        switch_cfg_topic,
        json.dumps(switch_cfg),
        qos=1,
        retain=True,
    )

    #
    # Closed sensor
    #
    closed_sensor_cfg_topic = (
        f"{prefix}/binary_sensor/{node_id}/closed_sensor/config"
    )

    closed_sensor_cfg = {
        "name": "Garage Door Closed Sensor",
        "unique_id": f"{node_id}_closed_sensor",
        "availability_topic": avail,
        "payload_available": "online",
        "payload_not_available": "offline",
        "state_topic": sensor_closed_topic,
        "payload_on": "ON",
        "payload_off": "OFF",
        "device": device,
    }

    c.publish(
        closed_sensor_cfg_topic,
        json.dumps(closed_sensor_cfg),
        qos=1,
        retain=True,
    )

    #
    # Open sensor
    #
    open_sensor_cfg_topic = (
        f"{prefix}/binary_sensor/{node_id}/open_sensor/config"
    )

    open_sensor_cfg = {
        "name": "Garage Door Open Sensor",
        "unique_id": f"{node_id}_open_sensor",
        "availability_topic": avail,
        "payload_available": "online",
        "payload_not_available": "offline",
        "state_topic": sensor_open_topic,
        "payload_on": "ON",
        "payload_off": "OFF",
        "device": device,
    }

    c.publish(
        open_sensor_cfg_topic,
        json.dumps(open_sensor_cfg),
        qos=1,
        retain=True,
    )