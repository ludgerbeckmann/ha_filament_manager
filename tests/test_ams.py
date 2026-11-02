"""The coupling of spools to AMS slots of the Bambu Lab integration."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.ha_filament_manager.const import DOMAIN

from .common import NUMBER, setup_with_spool

SLOT = "sensor.p1s_ams_1_tray_1"
SLOT2 = "sensor.p1s_ams_1_tray_2"
RFID_A = "0123456789ABCDEF0123456789ABCDEF"
RFID_B = "FEDCBA9876543210FEDCBA9876543210"
IN_PRINTER = "binary_sensor.test_spool_in_printer"


def register_slot(hass: HomeAssistant, entity_id: str = SLOT, unique_id: str = "P1S_0309_AMS_1_tray_1") -> None:
    """Register an AMS tray sensor the way the Bambu Lab integration does."""
    er.async_get(hass).async_get_or_create(
        "sensor", "bambu_lab", unique_id, suggested_object_id=entity_id.split(".", 1)[1]
    )


def set_slot(
    hass: HomeAssistant,
    entity_id: str = SLOT,
    *,
    rfid: str | None = RFID_A,
    remain: int = 80,
    empty: bool = False,
    state: str = "PLA Basic",
) -> None:
    hass.states.async_set(
        entity_id,
        state,
        {
            "empty": empty,
            "unknown": False,
            "tray_uuid": rfid or "0" * 32,
            "tag_uid": "1234567890ABCDEF" if rfid else "0" * 16,
            "remain": remain,
            "active": False,
        },
    )


async def setup_ams_spool(hass: HomeAssistant, **spool):
    register_slot(hass)
    return await setup_with_spool(hass, spool={"ams_slot": SLOT, **spool})


async def test_spool_is_in_the_printer_while_its_rfid_is_in_the_slot(hass: HomeAssistant) -> None:
    set_slot(hass, rfid=RFID_A)
    await setup_ams_spool(hass)
    assert hass.states.get(IN_PRINTER).state == "on"
    assert hass.states.get(IN_PRINTER).attributes["ams_slot"] == SLOT
    assert hass.states.get(IN_PRINTER).attributes["rfid_known"] is True

    set_slot(hass, empty=True)
    await hass.async_block_till_done()
    assert hass.states.get(IN_PRINTER).state == "off"

    set_slot(hass, rfid=RFID_B)  # another spool in the slot is not this one
    await hass.async_block_till_done()
    assert hass.states.get(IN_PRINTER).state == "off"

    set_slot(hass, rfid=RFID_A)
    await hass.async_block_till_done()
    assert hass.states.get(IN_PRINTER).state == "on"

    set_slot(hass, rfid=None)  # a spool without RFID is not our RFID spool either
    await hass.async_block_till_done()
    assert hass.states.get(IN_PRINTER).state == "off"

    hass.states.async_set(SLOT, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(IN_PRINTER).state == "unavailable"


async def test_spool_without_rfid_counts_as_loaded_when_the_slot_is_not_empty(hass: HomeAssistant) -> None:
    set_slot(hass, rfid=None, remain=-1)
    await setup_ams_spool(hass)
    state = hass.states.get(IN_PRINTER)
    assert state.state == "on"
    assert state.attributes["rfid_known"] is False
    assert state.attributes["ams_remaining_percent"] is None


async def test_remaining_weight_follows_the_ams_when_it_changes(hass: HomeAssistant) -> None:
    set_slot(hass, rfid=RFID_A, remain=80)
    await setup_ams_spool(hass)
    assert float(hass.states.get(NUMBER).state) == 750  # not at startup: the stored value stays

    set_slot(hass, rfid=RFID_A, remain=70)
    await hass.async_block_till_done()
    assert float(hass.states.get(NUMBER).state) == 700
    assert hass.states.get(NUMBER).attributes["remaining_percentage"] == 70.0

    await hass.services.async_call("number", "set_value", {"entity_id": NUMBER, "value": 650}, blocking=True)
    set_slot(hass, rfid=RFID_A, remain=70, state="PLA Basic (active)")  # same percentage: keep the manual value
    await hass.async_block_till_done()
    assert float(hass.states.get(NUMBER).state) == 650


async def test_remaining_weight_ignores_a_different_spool_or_a_switched_off_sync(hass: HomeAssistant) -> None:
    set_slot(hass, rfid=RFID_A, remain=80)
    entry, manager = await setup_ams_spool(hass)
    set_slot(hass, rfid=RFID_B, remain=40)
    await hass.async_block_till_done()
    assert float(hass.states.get(NUMBER).state) == 750

    (spool,) = manager.spools.values()
    manager.update_spool(spool.id, ams_sync=False)
    await hass.async_block_till_done()
    set_slot(hass, rfid=RFID_B, remain=60)
    await hass.async_block_till_done()
    set_slot(hass, rfid=RFID_B, remain=50)
    await hass.async_block_till_done()
    assert float(hass.states.get(NUMBER).state) == 750


async def test_refilling_forgets_the_rfid_of_the_old_spool(hass: HomeAssistant) -> None:
    set_slot(hass, rfid=RFID_A)
    await setup_ams_spool(hass)
    set_slot(hass, rfid=RFID_B)
    await hass.async_block_till_done()
    assert hass.states.get(IN_PRINTER).state == "off"

    await hass.services.async_call(DOMAIN, "refill_spool", {"entity_id": NUMBER}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(IN_PRINTER).state == "on"
    assert float(hass.states.get(NUMBER).state) == 1000


async def test_learned_rfid_survives_a_reload_but_not_a_slot_change(hass: HomeAssistant) -> None:
    set_slot(hass, rfid=RFID_A)
    entry, manager = await setup_ams_spool(hass)
    assert hass.states.get(IN_PRINTER).state == "on"
    await hass.async_block_till_done()

    set_slot(hass, rfid=RFID_B)  # another spool is put in while the integration reloads
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(IN_PRINTER).state == "off"

    # A different slot means a different spool: what was learned is dropped.
    register_slot(hass, SLOT2, "P1S_0309_AMS_1_tray_2")
    set_slot(hass, SLOT2, rfid=RFID_B, remain=90)
    manager = entry.runtime_data.manager  # the reload created a new inventory object
    (spool,) = manager.spools.values()
    manager.assign_slot(spool.id, SLOT2)
    await hass.async_block_till_done()
    assert hass.states.get(IN_PRINTER).state == "on"


async def test_in_printer_entity_follows_the_slot_assignment(hass: HomeAssistant) -> None:
    set_slot(hass, rfid=RFID_A)
    entry, manager = await setup_ams_spool(hass)
    registry = er.async_get(hass)
    assert registry.async_get(IN_PRINTER) is not None

    (spool,) = manager.spools.values()
    manager.assign_slot(spool.id, None)
    await hass.async_block_till_done()
    assert registry.async_get(IN_PRINTER) is None
    assert hass.states.get(IN_PRINTER) is None

    manager.assign_slot(spool.id, SLOT)
    await hass.async_block_till_done()
    assert hass.states.get(IN_PRINTER).state == "on"


async def test_a_slot_holds_one_spool(hass: HomeAssistant) -> None:
    set_slot(hass, rfid=None)
    entry, manager = await setup_ams_spool(hass)
    (first,) = manager.spools.values()
    (box,) = manager.boxes.values()
    second = manager.add_spool(
        name="Second Spool", material="PETG", color="Rot", manufacturer="Elegoo", box_id=box.id
    )
    manager.assign_slot(second.id, SLOT)
    await hass.async_block_till_done()

    assert first.ams_slot is None
    assert second.ams_slot == SLOT
    assert hass.states.get(IN_PRINTER) is None
    assert hass.states.get("binary_sensor.second_spool_in_printer").state == "on"
