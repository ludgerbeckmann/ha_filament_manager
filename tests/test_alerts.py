"""Humidity and low-stock alerts, and their notifications."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components import persistent_notification as pn
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.ha_filament_manager.const import (
    DEFAULT_HUMIDITY_DELAY,
    DEFAULT_HUMIDITY_MAX,
    DOMAIN,
)

from .common import NUMBER, setup_inventory, setup_with_spool

ALERT = "binary_sensor.test_box_humidity_alert"
LOW_STOCK = "binary_sensor.test_spool_low_stock_alert"
SENSOR = "sensor.dry_box_humidity"


async def _humid_box(hass: HomeAssistant, **settings):
    hass.states.async_set(SENSOR, "30")
    return await setup_with_spool(
        hass, box={"humidity_sensor": SENSOR, "humidity_max": 40, "humidity_delay": 0, **settings}
    )


async def test_humidity_alert_only_exists_with_a_sensor(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass)
    assert hass.states.get(ALERT) is None

    (box,) = manager.boxes.values()
    hass.states.async_set(SENSOR, "30")
    manager.update_box(box.id, humidity_sensor=SENSOR)
    await hass.async_block_till_done()
    assert hass.states.get(ALERT).state == "off"

    manager.update_box(box.id, humidity_sensor="")
    await hass.async_block_till_done()
    assert hass.states.get(ALERT) is None


async def test_humidity_alert_tracks_source_sensor(hass: HomeAssistant) -> None:
    await _humid_box(hass)
    assert hass.states.get(ALERT).state == "off"
    hass.states.async_set(SENSOR, "55")
    await hass.async_block_till_done()
    state = hass.states.get(ALERT)
    assert state.state == "on"
    assert state.attributes["current_humidity"] == 55.0
    assert state.attributes["source_entity_id"] == SENSOR


async def test_humidity_alert_delay_ignores_short_spikes(hass: HomeAssistant) -> None:
    await _humid_box(hass, humidity_delay=30)
    hass.states.async_set(SENSOR, "55")
    await hass.async_block_till_done()
    assert hass.states.get(ALERT).state == "off"
    assert hass.states.get(ALERT).attributes["over_threshold"] is True

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=29))
    await hass.async_block_till_done()
    assert hass.states.get(ALERT).state == "off"

    # A dip below the threshold restarts the grace period.
    hass.states.async_set(SENSOR, "30")
    await hass.async_block_till_done()
    hass.states.async_set(SENSOR, "55")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=29))
    await hass.async_block_till_done()
    assert hass.states.get(ALERT).state == "off"


async def test_humidity_alert_delay_fires_when_sustained(hass: HomeAssistant) -> None:
    await _humid_box(hass, humidity_delay=30)
    hass.states.async_set(SENSOR, "55")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done()
    assert hass.states.get(ALERT).state == "on"

    hass.states.async_set(SENSOR, "60")
    await hass.async_block_till_done()
    assert hass.states.get(ALERT).state == "on"
    hass.states.async_set(SENSOR, "30")
    await hass.async_block_till_done()
    assert hass.states.get(ALERT).state == "off"


async def test_limits_follow_the_most_sensitive_material_inside(hass: HomeAssistant) -> None:
    hass.states.async_set(SENSOR, "30")
    entry, runtime = await setup_inventory(hass)
    manager = runtime.manager
    box = manager.add_box("Test Box", humidity_sensor=SENSOR)
    await hass.async_block_till_done()

    attributes = hass.states.get(ALERT).attributes  # empty box: generic defaults
    assert attributes["threshold"] == DEFAULT_HUMIDITY_MAX
    assert attributes["delay_minutes"] == DEFAULT_HUMIDITY_DELAY

    # Nylon (20 %, 10 min) dominates PLA (50 %, 60 min) in the same box.
    details = {"color": "Rot", "manufacturer": "Elegoo", "box_id": box.id}
    manager.add_spool(name="PLA", material="PLA", **details)
    nylon = manager.add_spool(name="Nylon", material="Nylon", **details)
    await hass.async_block_till_done()
    attributes = hass.states.get(ALERT).attributes
    assert (attributes["threshold"], attributes["delay_minutes"]) == (20, 10)

    manager.remove_spool(nylon.id)  # the limits relax again
    await hass.async_block_till_done()
    attributes = hass.states.get(ALERT).attributes
    assert (attributes["threshold"], attributes["delay_minutes"]) == (50, 60)


async def test_explicit_limits_override_the_automatic_ones_and_follow_edits(hass: HomeAssistant) -> None:
    entry, manager = await _humid_box(hass, humidity_max=45, humidity_delay=5)
    attributes = hass.states.get(ALERT).attributes
    assert (attributes["threshold"], attributes["delay_minutes"]) == (45, 5)

    (box,) = manager.boxes.values()
    manager.update_box(box.id, humidity_max=None, humidity_delay=None)  # back to automatic (PLA inside)
    await hass.async_block_till_done()
    attributes = hass.states.get(ALERT).attributes
    assert (attributes["threshold"], attributes["delay_minutes"]) == (50, 60)


async def test_changing_the_sensor_follows_the_new_one(hass: HomeAssistant) -> None:
    entry, manager = await _humid_box(hass)
    (box,) = manager.boxes.values()
    hass.states.async_set("sensor.other_humidity", "70")
    manager.update_box(box.id, humidity_sensor="sensor.other_humidity")
    await hass.async_block_till_done()
    assert hass.states.get(ALERT).state == "on"
    hass.states.async_set(SENSOR, "10")  # the old sensor no longer matters
    await hass.async_block_till_done()
    assert hass.states.get(ALERT).state == "on"


async def test_humidity_alert_notifies_and_dismisses(hass: HomeAssistant) -> None:
    sent = []

    async def _fake_send_message(call):
        sent.append(dict(call.data))

    hass.services.async_register("notify", "send_message", _fake_send_message)
    events = []
    async_dispatcher_connect(
        hass, pn.SIGNAL_PERSISTENT_NOTIFICATIONS_UPDATED, lambda kind, items: events.append(kind)
    )
    entry, manager = await _humid_box(hass)
    manager.set_alert_settings(targets=["notify.fake_target"], persistent=True)

    hass.states.async_set(SENSOR, "55")
    await hass.async_block_till_done()
    assert len(sent) == 1
    assert sent[0]["entity_id"] == "notify.fake_target"
    assert "55" in sent[0]["message"]
    assert events.count(pn.UpdateType.ADDED) == 1

    hass.states.async_set(SENSOR, "30")
    await hass.async_block_till_done()
    assert len(sent) == 1  # nothing pushed on the falling edge ...
    assert events.count(pn.UpdateType.REMOVED) == 1  # ... but the persistent one is dismissed


async def test_low_stock_alert_exists_only_with_a_threshold_and_tracks_it(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass)
    assert hass.states.get(LOW_STOCK) is None

    (spool,) = manager.spools.values()
    manager.update_spool(spool.id, low_stock_threshold=20)
    await hass.async_block_till_done()
    assert hass.states.get(LOW_STOCK).state == "off"  # 75 % left

    await hass.services.async_call(DOMAIN, "consume_filament", {"entity_id": NUMBER, "amount": 650}, blocking=True)
    state = hass.states.get(LOW_STOCK)
    assert state.state == "on"
    assert state.attributes["remaining_percentage"] == 10.0

    manager.update_spool(spool.id, low_stock_threshold=5)  # a new threshold applies at the next change
    await hass.services.async_call(DOMAIN, "consume_filament", {"entity_id": NUMBER, "amount": 1}, blocking=True)
    assert hass.states.get(LOW_STOCK).state == "off"

    manager.update_spool(spool.id, low_stock_threshold="")
    await hass.async_block_till_done()
    assert hass.states.get(LOW_STOCK) is None
    assert er.async_get(hass).async_get(LOW_STOCK) is None


async def test_low_stock_alert_notifies(hass: HomeAssistant) -> None:
    sent = []

    async def _fake_send_message(call):
        sent.append(dict(call.data))

    hass.services.async_register("notify", "send_message", _fake_send_message)
    entry, manager = await setup_with_spool(hass, spool={"low_stock_threshold": 20})
    manager.set_alert_settings(targets=["notify.phone"])
    await hass.services.async_call(DOMAIN, "consume_filament", {"entity_id": NUMBER, "amount": 650}, blocking=True)
    await hass.async_block_till_done()
    assert len(sent) == 1
    assert sent[0]["entity_id"] == "notify.phone"
    assert "Bestand niedrig" in sent[0]["title"]


async def test_where_alerts_go_is_one_setting_for_every_box_and_spool(hass: HomeAssistant) -> None:
    sent = []

    async def _fake_send_message(call):
        sent.append(call.data["title"])

    hass.services.async_register("notify", "send_message", _fake_send_message)
    hass.states.async_set(SENSOR, "30")
    hass.states.async_set("sensor.other_humidity", "30")
    entry, manager = await setup_with_spool(
        hass, box={"humidity_sensor": SENSOR, "humidity_max": 40, "humidity_delay": 0}, spool={"low_stock_threshold": 20}
    )
    manager.add_box("Second Box", humidity_sensor="sensor.other_humidity", humidity_max=40, humidity_delay=0)
    await hass.services.async_call(
        DOMAIN, "set_alert_notifications", {"notify_targets": ["notify.phone"], "persistent_notification": False}, blocking=True
    )
    await hass.async_block_till_done()

    hass.states.async_set(SENSOR, "60")  # a box ...
    hass.states.async_set("sensor.other_humidity", "60")  # ... and another one
    await hass.services.async_call(DOMAIN, "consume_filament", {"entity_id": NUMBER, "amount": 700}, blocking=True)  # a spool
    await hass.async_block_till_done()
    assert len(sent) == 3
    assert manager.alert_settings.targets == ["notify.phone"] and manager.alert_settings.persistent is False


async def test_targets_of_older_versions_become_the_common_ones(hass: HomeAssistant, hass_storage) -> None:
    """Until 1.3 every box and spool had its own targets."""
    hass_storage[f"{DOMAIN}.data"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.data",
        "data": {
            "boxes": [
                {"id": "b1", "name": "Box", "notify_targets": ["notify.a"], "persistent_notification": False},
                {"id": "b2", "name": "Box 2", "notify_targets": ["notify.b", "notify.a"], "persistent_notification": True},
            ],
            "spools": [],
        },
    }
    entry, runtime = await setup_inventory(hass)
    assert runtime.manager.alert_settings.targets == ["notify.a", "notify.b"]
    assert runtime.manager.alert_settings.persistent is True
