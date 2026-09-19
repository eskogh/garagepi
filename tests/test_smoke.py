from dataclasses import replace


def test_import():
    import garagepi

    assert hasattr(garagepi, "__version__")


def test_pulse_if_allowed_blocks_second_pulse(monkeypatch):
    from garagepi import app as garage_app

    pulses = []
    monkeypatch.setattr(garage_app, "last_toggle", 0.0)
    monkeypatch.setattr(
        garage_app,
        "config",
        replace(garage_app.config, min_toggle_gap_s=10.0),
    )
    monkeypatch.setattr(garage_app.time, "time", lambda: 100.0)
    monkeypatch.setattr(garage_app, "pulse_trigger", lambda: pulses.append("pulse"))

    assert garage_app._pulse_if_allowed() is True
    assert garage_app._pulse_if_allowed() is False
    assert pulses == ["pulse"]


def test_check_door_status_reads_sensor_combinations():
    from garagepi import app as garage_app

    monkeypatch_config = replace(
        garage_app.config,
        sensor_open_pin=14,
        sensor_closed_pin=16,
    )
    garage_app.config = monkeypatch_config
    garage_app.sensor_snapshots = {
        "open": garage_app._empty_sensor("Open sensor", 14),
        "closed": garage_app._empty_sensor("Closed sensor", 16),
    }

    garage_app.GPIO.output(garage_app.config.sensor_open_pin, 1)
    garage_app.GPIO.output(garage_app.config.sensor_closed_pin, 0)
    assert garage_app.get_door_state() is garage_app.DoorState.OPEN
    assert garage_app.check_door_status() == "Open"

    garage_app.GPIO.output(garage_app.config.sensor_open_pin, 0)
    garage_app.GPIO.output(garage_app.config.sensor_closed_pin, 1)
    assert garage_app.get_door_state() is garage_app.DoorState.CLOSED
    assert garage_app.check_door_status() == "Closed"

    garage_app.GPIO.output(garage_app.config.sensor_open_pin, 0)
    garage_app.GPIO.output(garage_app.config.sensor_closed_pin, 0)
    assert garage_app.get_door_state() is garage_app.DoorState.MOVING
    assert garage_app.check_door_status() == "Moving"

    garage_app.GPIO.output(garage_app.config.sensor_open_pin, 1)
    garage_app.GPIO.output(garage_app.config.sensor_closed_pin, 1)
    assert garage_app.get_door_state() is garage_app.DoorState.UNKNOWN
    assert garage_app.check_door_status() == "Unknown"


def test_mqtt_cover_commands_are_state_aware(monkeypatch):
    from garagepi import app as garage_app

    pulses = []
    states = iter(
        [
            garage_app.DoorState.CLOSED,
            garage_app.DoorState.OPEN,
            garage_app.DoorState.MOVING,
            garage_app.DoorState.UNKNOWN,
        ]
    )
    monkeypatch.setattr(garage_app, "close_mode", False)
    monkeypatch.setattr(garage_app, "get_door_state", lambda: next(states))
    monkeypatch.setattr(garage_app, "_pulse_if_allowed", lambda: pulses.append("pulse"))

    garage_app._handle_cover_command("OPEN")
    garage_app._handle_cover_command("CLOSE")
    garage_app._handle_cover_command("STOP")
    garage_app._handle_cover_command("OPEN")

    assert pulses == ["pulse", "pulse", "pulse"]


def test_publish_state_if_changed_only_publishes_changed_state(monkeypatch):
    from garagepi import app as garage_app

    class FakeClient:
        def __init__(self):
            self.published = []

        def publish(self, *args, **kwargs):
            self.published.append((args, kwargs))

    client = FakeClient()
    states = iter(
        [
            garage_app.DoorState.CLOSED,
            garage_app.DoorState.CLOSED,
            garage_app.DoorState.OPEN,
        ]
    )
    monkeypatch.setattr(garage_app, "_mq", client)
    monkeypatch.setattr(garage_app, "_last_published_state", None)
    monkeypatch.setattr(garage_app, "get_door_state", lambda: next(states))

    garage_app._publish_state_if_changed()
    garage_app._publish_state_if_changed()
    garage_app._publish_state_if_changed()

    assert client.published == [
        (
            (garage_app.config.topics.cover_state, "closed"),
            {"qos": 1, "retain": True},
        ),
        (
            (garage_app.config.topics.cover_state, "open"),
            {"qos": 1, "retain": True},
        ),
    ]


def test_plate_watcher_does_not_open_on_unknown(monkeypatch):
    from automation import plate_watcher

    monkeypatch.setattr(plate_watcher, "last_open_ts", 0.0)
    monkeypatch.setattr(plate_watcher, "OPEN_COOLDOWN_S", 30.0)
    monkeypatch.setattr(plate_watcher, "door_status", lambda: "Unknown")

    assert plate_watcher.safe_to_open(100.0) is False
