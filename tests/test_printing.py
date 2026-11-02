"""The print notification (Live Activity) built on the Bambu Lab integration's sensors."""
from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.ha_filament_manager.const import DOMAIN
from custom_components.ha_filament_manager.printing import format_remaining, friendly_name, notify_services, printers

from .common import setup_inventory, setup_with_spool
from .test_ams import SLOT, register_slot, set_slot

SERIAL = "01P09C482100602"
STATUS = "sensor.p1s_druckstatus"
PROGRESS = "sensor.p1s_druckfortschritt"
REMAINING = "sensor.p1s_verbleibende_zeit"
JOB = "sensor.p1s_name_der_aufgabe"


def register_printer(hass: HomeAssistant) -> None:
    """The sensors of a Bambu Lab printer, as the Bambu Lab integration registers them."""
    bambu = MockConfigEntry(domain="bambu_lab")
    bambu.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=bambu.entry_id, identifiers={("bambu_lab", SERIAL)}, name="Bambu P1S"
    )
    registry = er.async_get(hass)
    for key, entity_id in (
        ("print_status", STATUS),
        ("print_progress", PROGRESS),
        ("remaining_time", REMAINING),
        ("subtask_name", JOB),
    ):
        registry.async_get_or_create(
            "sensor", "bambu_lab", f"{SERIAL}_{key}", config_entry=bambu, device_id=device.id,
            suggested_object_id=entity_id.split(".", 1)[1],
        )


def set_print(hass: HomeAssistant, status: str, progress: int = 0, *, minutes: float = 0, job: str = "Frame.3mf") -> None:
    hass.states.async_set(STATUS, status)
    hass.states.async_set(PROGRESS, str(progress))
    hass.states.async_set(REMAINING, str(minutes), {"unit_of_measurement": "min"})
    hass.states.async_set(JOB, job)


async def settle(hass: HomeAssistant) -> None:
    """Let the (debounced) notifier look at what the printer says."""
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()


@pytest.fixture
def sent(hass: HomeAssistant) -> list[tuple[str, dict]]:
    """Everything sent to the two Companion apps (notify.mobile_app_*) and to a plain notify service."""
    calls: list[tuple[str, dict]] = []

    def register(name: str) -> None:
        async def _handler(call):
            calls.append((name, dict(call.data)))

        hass.services.async_register("notify", name, _handler)

    for name in ("mobile_app_iphone", "mobile_app_ipad", "send_message"):
        register(name)
    return calls


async def configured(hass: HomeAssistant, **settings):
    register_printer(hass)
    set_print(hass, "idle")
    entry, runtime = await setup_inventory(hass)
    runtime.manager.set_print_settings(
        **{
            "enabled": True,
            "targets": ["mobile_app_iphone", "mobile_app_ipad"],
            "url": "/3d-drucker",
            "countdown": False,  # the texts below are the ones without the running countdown
            **settings,
        }
    )
    await hass.async_block_till_done()
    return runtime


def test_remaining_time_text() -> None:
    assert [format_remaining(m) for m in (0, 5, 59.9, 60, 65, 125)] == ["", "5 min", "59 min", "1 h 0 min", "1 h 5 min", "2 h 5 min"]


async def test_printers_and_targets_are_found(hass: HomeAssistant, sent) -> None:
    register_printer(hass)
    assert [(p.serial, p.name) for p in printers(hass)] == [(SERIAL, "Bambu P1S")]
    assert notify_services(hass) == ["mobile_app_ipad", "mobile_app_iphone"]  # only the Companion apps


async def test_a_running_print_is_shown_as_live_activity_on_every_target(hass: HomeAssistant, sent) -> None:
    await configured(hass)
    set_print(hass, "running", 42, minutes=65)
    await settle(hass)

    assert sorted(name for name, _ in sent) == ["mobile_app_ipad", "mobile_app_iphone"]
    payload = sent[0][1]
    assert payload["title"] == "Bambu P1S"
    assert payload["message"] == "noch 1 h 5 min · Frame.3mf"
    assert payload["data"] == {
        "tag": f"{DOMAIN}_print_{SERIAL}",
        "live_update": True,
        "progress": 42,
        "progress_max": 100,
        "critical_text": "42 %",
        "notification_icon": "mdi:printer-3d",
        "notification_icon_color": "#00AE42",
        "silent": True,
        "url": "/3d-drucker",
    }


async def test_only_changes_are_sent(hass: HomeAssistant, sent) -> None:
    await configured(hass)
    set_print(hass, "running", 42, minutes=65)
    await settle(hass)
    sent.clear()

    set_print(hass, "running", 42, minutes=65)  # nothing changed
    await settle(hass)
    assert not sent
    set_print(hass, "running", 43, minutes=64)
    await settle(hass)
    assert len(sent) == 2 and sent[0][1]["data"]["progress"] == 43 and "1 h 4 min" in sent[0][1]["message"]


async def test_pause_and_preparation_have_their_own_texts(hass: HomeAssistant, sent) -> None:
    await configured(hass)
    set_print(hass, "prepare", 0)
    await settle(hass)
    assert sent[-1][1]["message"] == "Vorbereitung · Frame.3mf"
    set_print(hass, "pause", 30, minutes=20)
    await settle(hass)
    assert sent[-1][1]["message"] == "⏸ Pausiert · Frame.3mf"
    assert sent[-1][1]["data"]["notification_icon_color"] == "#FF9800"


async def test_the_remaining_time_unit_is_taken_into_account(hass: HomeAssistant, sent) -> None:
    await configured(hass)
    hass.states.async_set(STATUS, "running")
    hass.states.async_set(PROGRESS, "10")
    hass.states.async_set(JOB, "Frame.3mf")
    hass.states.async_set(REMAINING, "1.5", {"unit_of_measurement": "h"})
    await settle(hass)
    assert sent[0][1]["message"] == "noch 1 h 30 min · Frame.3mf"


async def test_a_finished_print_clears_the_live_activity_and_announces_the_end_once(hass: HomeAssistant, sent) -> None:
    await configured(hass)
    set_print(hass, "running", 99, minutes=1)
    await settle(hass)
    sent.clear()

    set_print(hass, "finish", 100)
    await settle(hass)
    iphone = [payload for name, payload in sent if name == "mobile_app_iphone"]
    assert iphone[0] == {"message": "clear_notification", "data": {"tag": f"{DOMAIN}_print_{SERIAL}"}}
    assert iphone[1] == {"title": "✅ Bambu P1S – Druck fertig", "message": "Frame.3mf", "data": {"url": "/3d-drucker"}}
    assert len(sent) == 4

    sent.clear()
    set_print(hass, "finish", 100, job="Frame.3mf")  # the same end, seen again
    await settle(hass)
    assert not sent

    set_print(hass, "idle")  # nothing to clear: no Live Activity is showing any more
    await settle(hass)
    assert not sent


async def test_a_failed_print_is_announced(hass: HomeAssistant, sent) -> None:
    await configured(hass)
    set_print(hass, "running", 50, minutes=30)
    await settle(hass)
    sent.clear()
    set_print(hass, "failed", 50)
    await settle(hass)
    assert sent[2][1]["title"] == "❌ Bambu P1S – Druck fehlgeschlagen"


async def test_going_idle_or_offline_clears_a_showing_live_activity(hass: HomeAssistant, sent) -> None:
    await configured(hass)
    set_print(hass, "running", 50, minutes=30)
    await settle(hass)
    sent.clear()
    set_print(hass, "offline")
    await settle(hass)
    assert [payload["message"] for _, payload in sent] == ["clear_notification"] * 2


async def test_a_print_that_already_ended_is_not_announced_when_switching_on(hass: HomeAssistant, sent) -> None:
    register_printer(hass)
    set_print(hass, "finish", 100)
    entry, runtime = await setup_inventory(hass)
    runtime.manager.set_print_settings(enabled=True, targets=["mobile_app_iphone"])
    await settle(hass)
    assert not sent


async def test_nothing_is_sent_when_switched_off_or_without_targets(hass: HomeAssistant, sent) -> None:
    runtime = await configured(hass, enabled=False)
    set_print(hass, "running", 42, minutes=65)
    await settle(hass)
    runtime.manager.set_print_settings(enabled=True, targets=[])
    set_print(hass, "running", 43, minutes=64)
    await settle(hass)
    assert not sent


async def test_the_spool_in_use_is_named(hass: HomeAssistant, sent) -> None:
    register_slot(hass)
    register_printer(hass)
    set_print(hass, "idle")
    set_slot(hass, rfid=None)
    entry, manager = await setup_with_spool(hass, spool={"ams_slot": SLOT})
    manager.set_print_settings(enabled=True, targets=["mobile_app_iphone"], countdown=False)
    await hass.async_block_till_done()

    hass.states.async_set(SLOT, "PLA Basic", {**hass.states.get(SLOT).attributes, "active": True})
    set_print(hass, "running", 10, minutes=30)
    await settle(hass)
    assert sent[-1][1]["message"] == "noch 30 min · Frame.3mf · Test Spool (75 %)"

    manager.set_print_settings(show_filament=False)
    set_print(hass, "running", 11, minutes=29)
    await settle(hass)
    assert sent[-1][1]["message"] == "noch 29 min · Frame.3mf"


async def test_a_missing_notify_service_does_not_stop_the_others(hass: HomeAssistant, sent) -> None:
    await configured(hass, targets=["mobile_app_gone", "mobile_app_ipad"])
    set_print(hass, "running", 42, minutes=65)
    await settle(hass)
    assert [name for name, _ in sent] == ["mobile_app_ipad"]


async def test_the_test_notification_is_removed_again(hass: HomeAssistant, sent) -> None:
    await configured(hass, countdown=False)
    await hass.services.async_call(DOMAIN, "test_print_notification", {}, blocking=True)
    assert len(sent) == 2
    assert sent[0][1]["message"] == "noch 1 h 5 min · Testdruck · PETG Rot (82 %)"
    assert sent[0][1]["data"]["progress"] == 42

    sent.clear()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert [payload["message"] for _, payload in sent] == ["clear_notification"] * 2


async def test_the_test_notification_needs_targets(hass: HomeAssistant, sent) -> None:
    entry, runtime = await setup_inventory(hass)
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(DOMAIN, "test_print_notification", {}, blocking=True)
    assert error.value.translation_key == "no_print_targets"


async def test_settings_are_saved_through_the_service_and_shown_in_the_snapshot(
    hass: HomeAssistant, hass_ws_client, hass_storage, sent
) -> None:
    register_printer(hass)
    entry, runtime = await setup_inventory(hass)
    await hass.services.async_call(
        DOMAIN,
        "set_print_notification",
        {"enabled": True, "targets": ["mobile_app_iphone"], "url": " /3d ", "show_filament": False, "printer": SERIAL},
        blocking=True,
    )
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/subscribe"})
    assert (await client.receive_json())["success"]
    snapshot = (await client.receive_json())["event"]["print_notification"]
    assert snapshot == {
        "enabled": True,
        "printer": SERIAL,
        "targets": ["mobile_app_iphone"],
        "name": "",
        "url": "/3d",
        "show_filament": False,
        "countdown": True,
        "printers": [{"serial": SERIAL, "name": "Bambu P1S"}],
        "notify_services": ["mobile_app_ipad", "mobile_app_iphone"],
    }

    await runtime.manager.async_flush()
    assert hass_storage[f"{DOMAIN}.data"]["data"]["print_notification"]["targets"] == ["mobile_app_iphone"]


def test_the_printer_name_loses_its_serial_number() -> None:
    assert friendly_name("P1S_01P09C482100602", "01P09C482100602") == "Bambu Lab P1S"
    assert friendly_name("A1 mini 01P09C482100602", "01P09C482100602") == "Bambu Lab A1 mini"
    assert friendly_name("Bambu P1S", "01P09C482100602") == "Bambu P1S"
    assert friendly_name("Werkstatt-Drucker 01p09c482100602", "01P09C482100602") == "Werkstatt-Drucker"
    assert friendly_name("01P09C482100602", "01P09C482100602") == "01P09C482100602"


async def test_a_name_of_your_own_is_the_title(hass: HomeAssistant, sent) -> None:
    await configured(hass, name="Drucker im Keller")
    set_print(hass, "running", 42, minutes=65)
    await settle(hass)
    assert sent[0][1]["title"] == "Drucker im Keller"
    sent.clear()
    set_print(hass, "finish", 100)
    await settle(hass)
    assert sent[2][1]["title"] == "✅ Drucker im Keller – Druck fertig"


async def test_the_countdown_runs_on_the_device(hass: HomeAssistant, sent, freezer) -> None:
    freezer.move_to("2026-11-02 12:00:00+00:00")
    await configured(hass, countdown=True)
    set_print(hass, "running", 42, minutes=65)
    await settle(hass)

    payload = sent[0][1]
    eta = dt_util.as_local(dt_util.utcnow() + timedelta(minutes=65)).strftime("%H:%M")
    assert payload["message"] == f"Druckt · fertig ca. {eta} · Frame.3mf"
    data = payload["data"]
    assert data["chronometer"] is True
    assert data["when_relative"] is False
    assert data["when"] == int(dt_util.utcnow().timestamp()) + 65 * 60

    # A paused print has no running clock.
    set_print(hass, "pause", 42, minutes=65)
    await settle(hass)
    assert "chronometer" not in sent[-1][1]["data"]
    assert sent[-1][1]["message"] == "⏸ Pausiert · Frame.3mf"


async def test_the_end_of_a_long_print_names_the_day(hass: HomeAssistant, sent, freezer) -> None:
    freezer.move_to("2026-11-02 12:00:00+00:00")
    await configured(hass, countdown=True)
    set_print(hass, "running", 10, minutes=60 * 30)
    await settle(hass)
    end = dt_util.as_local(dt_util.utcnow() + timedelta(minutes=60 * 30))
    assert f"fertig ca. {end.day}.{end.month}. {end:%H:%M}" in sent[0][1]["message"]
