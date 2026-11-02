"""The inventory: boxes, spools, the stock - and the entities that mirror them."""
from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.ha_filament_manager.const import DOMAIN
from custom_components.ha_filament_manager.store import FilamentError

from .common import BOX, NUMBER, SPOOL, device_id, setup_inventory, setup_with_spool


async def test_spool_in_a_box_gets_a_device_below_the_box_and_a_number(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass)
    (box,) = manager.boxes.values()
    (spool,) = manager.spools.values()

    state = hass.states.get(NUMBER)
    assert float(state.state) == 750.0
    assert state.attributes["material"] == "PLA"
    assert state.attributes["remaining_percentage"] == 75.0
    assert state.attributes["box"] == BOX
    assert state.attributes["max"] == 1000

    registry = dr.async_get(hass)
    box_device = registry.async_get(device_id(hass, entry, box.id))
    spool_device = registry.async_get(device_id(hass, entry, spool.id))
    assert box_device.name == BOX
    assert spool_device.name == SPOOL
    assert spool_device.via_device_id == box_device.id
    assert hass.states.get("sensor.test_box_spools").state == "1"
    # The old read-only sensors are attributes now.
    assert hass.states.get("sensor.test_spool_material") is None


async def test_remaining_weight_is_editable_and_persisted(hass: HomeAssistant, hass_storage) -> None:
    entry, manager = await setup_with_spool(hass)
    await hass.services.async_call("number", "set_value", {"entity_id": NUMBER, "value": 321}, blocking=True)
    assert float(hass.states.get(NUMBER).state) == 321.0
    assert next(iter(manager.spools.values())).remaining_weight == 321

    # Unloading the entry saves a pending change, so a reload does not lose it.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get(NUMBER).state) == 321.0
    stored = hass_storage[f"{DOMAIN}.data"]["data"]
    assert stored["spools"][0]["remaining_weight"] == 321


async def test_consume_and_refill_services(hass: HomeAssistant) -> None:
    await setup_with_spool(hass)
    await hass.services.async_call(DOMAIN, "consume_filament", {"entity_id": NUMBER, "amount": 100}, blocking=True)
    assert float(hass.states.get(NUMBER).state) == 650.0
    await hass.services.async_call(DOMAIN, "consume_filament", {"entity_id": NUMBER, "amount": 5000}, blocking=True)
    assert float(hass.states.get(NUMBER).state) == 0.0  # never below zero
    await hass.services.async_call(DOMAIN, "refill_spool", {"entity_id": NUMBER}, blocking=True)
    assert float(hass.states.get(NUMBER).state) == 1000.0
    await hass.services.async_call(DOMAIN, "refill_spool", {"entity_id": NUMBER, "amount": 400}, blocking=True)
    assert float(hass.states.get(NUMBER).state) == 400.0


async def test_entities_do_not_poll(hass: HomeAssistant) -> None:
    """Everything updates by event; no entity should be asked every 30 seconds."""
    await setup_with_spool(hass, spool={"low_stock_threshold": 10})

    for entity_id in (NUMBER, "sensor.test_box_spools", "binary_sensor.test_spool_low_stock_alert"):
        assert hass.states.get(entity_id) is not None
    platforms = hass.data["entity_platform"][DOMAIN]
    assert not any(platform._async_polling_timer for platform in platforms)


async def test_sealed_spools_are_stock_without_devices(hass: HomeAssistant) -> None:
    entry, runtime = await setup_inventory(hass)
    manager = runtime.manager
    manager.add_spool(name="Neu", material="PETG", color="Rot", manufacturer="Elegoo", sealed=True)
    manager.add_spool(name="Neu 2", material="PETG", color="Blau", manufacturer="Elegoo", sealed=True)
    manager.add_spool(name="Neu 3", material="PLA", color="Blau", manufacturer="Elegoo", sealed=True)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.vorrat_sealed_spools")
    assert state.state == "3"
    assert state.attributes["by_material"] == {"PETG": 2, "PLA": 1}
    assert hass.states.get("number.neu_remaining_weight") is None
    assert all(not spool.box_id for spool in manager.spools.values())


async def test_opening_a_sealed_spool_gives_it_a_device_in_the_box(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass)
    (box,) = manager.boxes.values()
    sealed = manager.add_spool(name="Neu", material="PETG", color="Rot", manufacturer="Elegoo", sealed=True)
    await hass.async_block_till_done()
    assert hass.states.get("number.neu_remaining_weight") is None

    manager.move_spool(sealed.id, box.id)
    await hass.async_block_till_done()
    assert float(hass.states.get("number.neu_remaining_weight").state) == 1000.0
    assert hass.states.get("sensor.vorrat_sealed_spools").state == "0"
    assert hass.states.get("sensor.test_box_spools").state == "2"
    assert not sealed.sealed and sealed.box_id == box.id


async def test_moving_a_spool_keeps_its_entities_and_relinks_the_device(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass)
    other = manager.add_box("Second Box")
    (spool,) = manager.spools.values()
    await hass.async_block_till_done()
    ent_id = er.async_get(hass).async_get(NUMBER).id

    manager.move_spool(spool.id, other.id)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(NUMBER).id == ent_id  # same entity
    assert hass.states.get(NUMBER).attributes["box"] == "Second Box"
    registry = dr.async_get(hass)
    assert registry.async_get(device_id(hass, entry, spool.id)).via_device_id == device_id(hass, entry, other.id)
    assert hass.states.get("sensor.test_box_spools").state == "0"
    assert hass.states.get("sensor.second_box_spools").state == "1"


async def test_renaming_updates_the_devices(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass)
    (box,) = manager.boxes.values()
    (spool,) = manager.spools.values()
    manager.update_box(box.id, name="Renamed Box")
    manager.update_spool(spool.id, name="Renamed Spool")
    await hass.async_block_till_done()
    registry = dr.async_get(hass)
    assert registry.async_get(device_id(hass, entry, box.id)).name == "Renamed Box"
    assert registry.async_get(device_id(hass, entry, spool.id)).name == "Renamed Spool"


async def test_removing_a_spool_or_box_removes_devices_and_entities(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass)
    (box,) = manager.boxes.values()
    (spool,) = manager.spools.values()

    with pytest.raises(FilamentError) as error:
        manager.remove_box(box.id)
    assert error.value.key == "box_not_empty"

    manager.remove_spool(spool.id)
    await hass.async_block_till_done()
    assert hass.states.get(NUMBER) is None
    assert er.async_get(hass).async_get(NUMBER) is None
    manager.remove_box(box.id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test_box_spools") is None
    assert not [d for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id) if d.name == BOX]


async def test_spool_limit_and_validation(hass: HomeAssistant) -> None:
    entry, runtime = await setup_inventory(hass)
    manager = runtime.manager
    box = manager.add_box("Small", spool_limit=1)
    details = {"material": "PLA", "color": "Rot", "manufacturer": "Elegoo"}
    manager.add_spool(name="One", box_id=box.id, **details)

    def key(action) -> str:
        with pytest.raises(FilamentError) as error:
            action()
        return error.value.key

    assert key(lambda: manager.add_spool(name="Two", box_id=box.id, **details)) == "box_full"
    assert key(lambda: manager.add_spool(name="Two", **details)) == "box_required"
    assert key(lambda: manager.add_spool(name="Two", box_id="nope", **details)) == "box_not_found"
    assert key(lambda: manager.add_spool(name="X", sealed=True, total_weight=100, remaining_weight=200, **details)) == "remaining_exceeds_total"
    assert key(lambda: manager.add_box("  ")) == "name_required"
    other = manager.add_box("Other")
    sealed = manager.add_spool(name="S", sealed=True, **details)
    assert key(lambda: manager.move_spool(sealed.id, box.id)) == "box_full"
    assert key(lambda: manager.assign_slot(sealed.id, "sensor.x")) == "spool_sealed"
    manager.add_spool(name="Three", box_id=other.id, **details)
    manager.add_spool(name="Four", box_id=other.id, **details)
    assert key(lambda: manager.update_box(other.id, spool_limit=1)) == "limit_below_count"


async def test_total_weight_change_caps_the_remaining_weight(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass)
    (spool,) = manager.spools.values()
    manager.update_spool(spool.id, total_weight=500)
    await hass.async_block_till_done()
    assert float(hass.states.get(NUMBER).state) == 500.0
    assert hass.states.get(NUMBER).attributes["max"] == 500


async def test_nothing_uses_deprecated_home_assistant_apis(hass: HomeAssistant, caplog) -> None:
    """Home Assistant logs a warning for deprecated calls of custom integrations (e.g. via_device)."""
    entry, manager = await setup_with_spool(hass, spool={"low_stock_threshold": 10, "ams_slot": None})
    other = manager.add_box("Second Box")
    (spool,) = manager.spools.values()
    manager.move_spool(spool.id, other.id)
    await hass.async_block_till_done()
    assert "Detected that custom integration" not in caplog.text
    assert "via_device" not in caplog.text
