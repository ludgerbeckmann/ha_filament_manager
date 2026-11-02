"""The management services and the websocket API the dashboard card uses."""
from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component

from custom_components.ha_filament_manager.const import CARD_URL_PATH, DOMAIN

from .common import BOX, NUMBER, SPOOL, device_id, setup_inventory, setup_with_spool
from .test_ams import SLOT, register_slot, set_slot


async def call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)
    await hass.async_block_till_done()


async def test_boxes_can_be_added_edited_and_removed(hass: HomeAssistant) -> None:
    entry, runtime = await setup_inventory(hass)
    manager = runtime.manager
    await call(hass, "add_box", name="Box A", humidity_max=45, spool_limit=3, notify_targets=["notify.me"])
    (box,) = manager.boxes.values()
    assert (box.name, box.humidity_max, box.spool_limit, box.notify_targets) == ("Box A", 45, 3, ["notify.me"])
    assert hass.states.get("sensor.box_a_spools").state == "0"

    await call(hass, "update_box", box=box.id, name="Box B", spool_limit="", humidity_max="")
    assert (box.name, box.humidity_max, box.spool_limit) == ("Box B", None, None)

    await call(hass, "remove_box", box=device_id(hass, entry, box.id))  # by device id, too
    assert not manager.boxes


async def test_a_spool_goes_into_a_box_or_the_stock(hass: HomeAssistant) -> None:
    entry, runtime = await setup_inventory(hass)
    manager = runtime.manager
    await call(hass, "add_box", name=BOX)
    (box,) = manager.boxes.values()

    await call(hass, "add_spool", box=box.id, material="TPU", color="Rot", manufacturer="Elegoo")
    await call(hass, "add_spool", material="PLA", color="Blau", manufacturer="Elegoo", total_weight=750)
    in_box = next(s for s in manager.spools.values() if not s.sealed)
    sealed = next(s for s in manager.spools.values() if s.sealed)
    assert (in_box.name, in_box.total_weight, in_box.remaining_weight) == ("Elegoo TPU Rot", 500, 500)
    assert (sealed.name, sealed.box_id, sealed.total_weight) == ("Elegoo PLA Blau", None, 750)

    await call(hass, "open_spool", spool=sealed.id, box=device_id(hass, entry, box.id))
    assert not sealed.sealed and sealed.box_id == box.id
    assert hass.states.get("sensor.test_box_spools").state == "2"


async def test_update_and_remove_a_spool(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass)
    (spool,) = manager.spools.values()
    await call(hass, "update_spool", spool=spool.id, name="New Name", low_stock_threshold=15, total_weight=800)
    assert (spool.name, spool.low_stock_threshold, spool.total_weight) == ("New Name", 15, 800)
    assert hass.states.get("binary_sensor.new_name_low_stock_alert") is not None
    assert float(hass.states.get("number.test_spool_remaining_weight").state) == 750

    await call(hass, "remove_spool", spool=device_id(hass, entry, spool.id))
    assert not manager.spools
    assert hass.states.get("number.test_spool_remaining_weight") is None


async def test_move_a_spool_with_the_service(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass)
    other = manager.add_box("Second Box")
    (spool,) = manager.spools.values()
    await call(hass, "move_spool", spool=spool.id, box=other.id)
    assert spool.box_id == other.id
    assert hass.states.get("sensor.second_box_spools").state == "1"


async def test_load_and_unload_a_spool(hass: HomeAssistant) -> None:
    register_slot(hass)
    set_slot(hass, rfid=None)
    entry, manager = await setup_with_spool(hass)
    (spool,) = manager.spools.values()

    await call(hass, "load_spool", spool=spool.id, slot=SLOT)
    assert spool.ams_slot == SLOT
    assert hass.states.get("binary_sensor.test_spool_in_printer").state == "on"

    with pytest.raises(ServiceValidationError):
        await call(hass, "load_spool", spool=spool.id, slot="sensor.not_a_slot")

    await call(hass, "unload_spool", spool=spool.id)
    assert spool.ams_slot is None
    assert hass.states.get("binary_sensor.test_spool_in_printer") is None


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("remove_spool", {"spool": "nope"}),
        ("move_spool", {"spool": "nope", "box": "nope"}),
        ("remove_box", {"box": "nope"}),
        ("add_spool", {"box": "nope", "material": "PLA", "color": "Rot", "manufacturer": "Elegoo"}),
    ],
)
async def test_unknown_ids_are_rejected(hass: HomeAssistant, service: str, data: dict) -> None:
    await setup_with_spool(hass)
    with pytest.raises(ServiceValidationError):
        await call(hass, service, **data)


async def test_rejections_are_translated_validation_errors(hass: HomeAssistant) -> None:
    entry, manager = await setup_with_spool(hass, box={"spool_limit": 1})
    (box,) = manager.boxes.values()
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "add_spool", box=box.id, material="PLA", color="Rot", manufacturer="Elegoo")
    assert error.value.translation_key == "box_full"
    assert error.value.translation_placeholders == {"box": BOX}

    with pytest.raises(ServiceValidationError) as error:
        await call(
            hass, "add_spool", material="PLA", color="Rot", manufacturer="Elegoo", total_weight=100, remaining_weight=200
        )
    assert error.value.translation_key == "remaining_exceeds_total"

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "remove_box", box=box.id)
    assert error.value.translation_key == "box_not_empty"


async def test_the_manufacturer_is_required(hass: HomeAssistant) -> None:
    await setup_with_spool(hass)
    with pytest.raises(Exception):  # noqa: B017 - the schema rejects it
        await call(hass, "add_spool", material="PLA", color="Rot")


# --- websocket ---------------------------------------------------------------


async def test_the_snapshot_describes_boxes_spools_and_slots(hass: HomeAssistant, hass_ws_client) -> None:
    register_slot(hass)
    entry, manager = await setup_with_spool(hass, box={"spool_limit": 4, "humidity_sensor": "sensor.h"})
    sealed = manager.add_spool(name="Neu", material="PETG", color="Rot", manufacturer="Elegoo", sealed=True)
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/subscribe"})
    assert (await client.receive_json())["success"]
    snapshot = (await client.receive_json())["event"]

    (box,) = snapshot["boxes"]
    assert (box["name"], box["count"], box["spool_limit"]) == (BOX, 1, 4)
    assert box["alert_entity"] == "binary_sensor.test_box_humidity_alert"
    assert box["effective_humidity_max"] == 50  # PLA inside
    by_name = {spool["name"]: spool for spool in snapshot["spools"]}
    assert by_name[SPOOL]["entity_id"] == NUMBER
    assert by_name[SPOOL]["percent"] == 75
    assert by_name["Neu"]["sealed"] and by_name["Neu"]["box_id"] is None and by_name["Neu"]["entity_id"] is None
    assert snapshot["slots"] == [SLOT]

    # Changes are pushed.
    manager.set_remaining(sealed.id, 400)
    event = (await client.receive_json())["event"]
    assert {spool["name"]: spool for spool in event["spools"]}["Neu"]["remaining_weight"] == 400


async def test_subscribe_needs_a_set_up_inventory(hass: HomeAssistant, hass_ws_client) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/subscribe"})
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "not_loaded"


async def test_options_and_suggestions(hass: HomeAssistant, hass_ws_client) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/options"})
    result = (await client.receive_json())["result"]
    assert result["materials"][0] == "ABS" and result["materials"][-1] == "Sonstiges"  # sorted, catch-all last
    assert result["manufacturers"][-1] == "Sonstiges"
    assert result["default_material"] == "PETG" and "Schwarz" in result["colors"]
    assert result["diameters"] == ["1.75", "2.85"]
    assert result["default_suggestion"] == {"name": "3DJake PETG Schwarz", "total_weight": 1000}

    await client.send_json(
        {"id": 2, "type": f"{DOMAIN}/suggest", "material": "TPU", "color": "Rot", "manufacturer": "Elegoo"}
    )
    assert (await client.receive_json())["result"] == {"name": "Elegoo TPU Rot", "total_weight": 500}


async def test_the_card_is_served_and_registered(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL

    assert any(url.startswith(CARD_URL_PATH) for url in hass.data[DATA_EXTRA_MODULE_URL].urls)
    client = await hass_client()
    resp = await client.get(CARD_URL_PATH)
    assert resp.status == 200
    body = await resp.text()
    assert 'customElements.define("filament-manager-card"' in body
    assert "/subscribe" in body and "show_stock" in body and "group_by" in body
    assert "set_print_notification" in body and "test_print_notification" in body
