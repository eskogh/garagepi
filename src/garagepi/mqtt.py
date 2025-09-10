import json

try:
    import paho.mqtt.client as mqttlib
except Exception:
    mqttlib = None


def connect(client_id: str, host: str, port: int, user: str = "", password: str = ""):
    if not mqttlib:
        return None
    client = mqttlib.Client(client_id=client_id, clean_session=True)
    if user:
        client.username_pw_set(user, password or None)
    client.connect(host, port, keepalive=30)
    client.loop_start()
    return client


def publish_discovery(
    c, prefix, node_id, avail, state_topic, cmd_topic, cm_state, cm_set
):
    if not c:
        return
    cover_cfg_topic = f"{prefix}/cover/{node_id}/cover/config"
    switch_cfg_topic = f"{prefix}/switch/{node_id}/close_mode/config"

    cover_cfg = {
        "name": "Garage Door",
        "unique_id": f"{node_id}_cover",
        "availability_topic": avail,
        "command_topic": cmd_topic,
        "state_topic": state_topic,
        "payload_open": "OPEN",
        "payload_close": "CLOSE",
        "payload_stop": "STOP",
        "state_open": "open",
        "state_closed": "closed",
        "state_opening": "opening",
        "state_closing": "closing",
        "device": {"identifiers": [node_id], "name": "GaragePi"},
    }
    switch_cfg = {
        "name": "Garage Close Mode",
        "unique_id": f"{node_id}_close_mode",
        "availability_topic": avail,
        "command_topic": cm_set,
        "state_topic": cm_state,
        "payload_on": "ON",
        "payload_off": "OFF",
        "device": {"identifiers": [node_id]},
    }
    c.publish(cover_cfg_topic, json.dumps(cover_cfg), qos=1, retain=True)
    c.publish(switch_cfg_topic, json.dumps(switch_cfg), qos=1, retain=True)
