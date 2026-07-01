def test_import():
    import garagepi

    assert hasattr(garagepi, "__version__")


def test_pulse_if_allowed_blocks_second_pulse(monkeypatch):
    from garagepi import app as garage_app

    pulses = []
    monkeypatch.setattr(garage_app, "last_toggle", 0.0)
    monkeypatch.setattr(garage_app, "MIN_TOGGLE_GAP_S", 10.0)
    monkeypatch.setattr(garage_app.time, "time", lambda: 100.0)
    monkeypatch.setattr(garage_app, "pulse_trigger", lambda: pulses.append("pulse"))

    assert garage_app._pulse_if_allowed() is True
    assert garage_app._pulse_if_allowed() is False
    assert pulses == ["pulse"]


def test_mqtt_cover_commands_are_state_aware(monkeypatch):
    from garagepi import app as garage_app

    pulses = []
    states = iter(["Closed", "Open", "Moving", "Unknown"])
    monkeypatch.setattr(garage_app, "close_mode", False)
    monkeypatch.setattr(garage_app, "check_door_status", lambda: next(states))
    monkeypatch.setattr(garage_app, "_pulse_if_allowed", lambda: pulses.append("pulse"))

    garage_app._handle_cover_command("OPEN")
    garage_app._handle_cover_command("CLOSE")
    garage_app._handle_cover_command("STOP")
    garage_app._handle_cover_command("OPEN")

    assert pulses == ["pulse", "pulse", "pulse"]


def test_plate_watcher_does_not_open_on_unknown(monkeypatch):
    from automation import plate_watcher

    monkeypatch.setattr(plate_watcher, "last_open_ts", 0.0)
    monkeypatch.setattr(plate_watcher, "OPEN_COOLDOWN_S", 30.0)
    monkeypatch.setattr(plate_watcher, "door_status", lambda: "Unknown")

    assert plate_watcher.safe_to_open(100.0) is False
