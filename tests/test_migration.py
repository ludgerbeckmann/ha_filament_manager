"""Versions before 1.0 had one config entry per box and one subentry per spool."""
from __future__ import annotations

import inspect

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.ha_filament_manager.const import DOMAIN

from .common import device_id
from .test_ams import RFID_A, SLOT, register_slot, set_slot


def _spool(subentry_id: str, title: str, **data) -> ConfigSubentryData:
    return ConfigSubentryData(
        data={
            "material": "PLA",
            "color": "Schwarz",
            "manufacturer": "Elegoo",
            "diameter": "1.75",
            "total_weight": 1000,
            "initial_remaining_weight": 900,
            **data,
        },
        subentry_id=subentry_id,
        subentry_type="spool",
        title=title,
        unique_id=None,
    )


def _legacy_hub(hass: HomeAssistant, title: str, spools: list[ConfigSubentryData], **data) -> MockConfigEntry:
    """A box entry as versions 0.x created it: box subentry + spool subentries, devices and entities."""
    box = ConfigSubentryData(data={}, subentry_id=f"box-{title}", subentry_type="box", title=f"# {title}", unique_id=None)
    hub = MockConfigEntry(domain=DOMAIN, title=title, data=data, subentries_data=[box, *spools])
    hub.add_to_hass(hass)
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)

    box_device = dev_reg.async_get_or_create(
        config_entry_id=hub.entry_id,
        config_subentry_id=box.get("subentry_id"),
        identifiers={(DOMAIN, hub.entry_id)},
        name=title,
    )
    ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{hub.entry_id}_spool_count", config_entry=hub,
        config_subentry_id=box.get("subentry_id"), device_id=box_device.id,
        suggested_object_id=f"{title.lower().replace(' ', '_')}_spools",
    )
    if data.get("humidity_sensor"):
        ent_reg.async_get_or_create(
            "binary_sensor", DOMAIN, f"{hub.entry_id}_humidity_alert", config_entry=hub,
            config_subentry_id=box.get("subentry_id"), device_id=box_device.id,
            suggested_object_id=f"{title.lower().replace(' ', '_')}_humidity_alert",
        )
    for spool in spools:
        sid = spool["subentry_id"]
        name = spool["title"].lower().replace(" ", "_")
        device = dev_reg.async_get_or_create(
            config_entry_id=hub.entry_id,
            config_subentry_id=sid,
            identifiers={(DOMAIN, sid)},
            name=spool["title"],
            **(
                {"via_device_id": box_device.id}
                if "via_device_id" in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters
                else {"via_device": (DOMAIN, hub.entry_id)}
            ),
        )
        for domain, suffix, object_id in (
            ("number", "remaining_weight", f"{name}_remaining_weight"),
            ("sensor", "remaining_percentage", f"{name}_remaining"),
            ("sensor", "material", f"{name}_material"),
            ("sensor", "color", f"{name}_color"),
            ("binary_sensor", "low_stock_alert", f"{name}_low_stock_alert"),
            ("binary_sensor", "in_printer", f"{name}_in_printer"),
        ):
            if suffix == "low_stock_alert" and spool["data"].get("low_stock_threshold") is None:
                continue
            if suffix == "in_printer" and not spool["data"].get("ams_slot"):
                continue
            ent_reg.async_get_or_create(
                domain, DOMAIN, f"{sid}_{suffix}", config_entry=hub, config_subentry_id=sid,
                device_id=device.id, suggested_object_id=object_id,
            )
    return hub


async def test_boxes_and_spools_are_carried_over_with_their_entities(hass: HomeAssistant, hass_storage) -> None:
    register_slot(hass)
    set_slot(hass, rfid=RFID_A)
    box_a = _legacy_hub(
        hass,
        "Box A",
        [
            _spool("spool1", "Spool One", ams_slot=SLOT, low_stock_threshold=20, cloud_spool=11,
                   notify_targets=["notify.me"], persistent_notification=True),
            _spool("spool2", "Spool Two", material="Nylon"),
        ],
        humidity_sensor="sensor.h", humidity_max=45, notify_targets=["notify.me"], spool_limit=5,
    )
    box_b = _legacy_hub(hass, "Box B", [_spool("spool3", "Spool Three")])
    # What the old versions had learned about the AMS and the cloud (one store per box).
    hass_storage[f"{DOMAIN}.ams_{box_a.entry_id}"] = {
        "version": 1, "minor_version": 1, "key": f"{DOMAIN}.ams_{box_a.entry_id}",
        "data": {"spool1": {"slot": SLOT, "rfid": RFID_A}},
    }
    hass.states.async_set("sensor.h", "30")
    mock_restore_cache(hass, [State("number.spool_one_remaining_weight", "321")])
    box_a_id, box_b_id = box_a.entry_id, box_b.entry_id
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    spool_device = device_id(hass, box_a, "spool1")

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    # One entry is left; it holds the inventory.
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert (entry.version, entry.unique_id, entry.title) == (2, "main", "Filament Manager")
    assert not entry.subentries and entry.state.value == "loaded"
    assert entry.entry_id == box_a_id  # the first box entry became the inventory entry ...
    assert hass.config_entries.async_get_entry(box_b_id) is None  # ... and the other one is gone
    assert hass_storage[f"{DOMAIN}.ams"]["data"] == {"spool1": {"slot": SLOT, "rfid": RFID_A}}
    assert f"{DOMAIN}.ams_{box_a_id}" not in hass_storage  # the per-box store was merged and removed

    manager = entry.runtime_data.manager
    box = manager.boxes[box_a_id]  # the box keeps its old id
    assert (box.name, box.humidity_sensor, box.humidity_max, box.spool_limit) == ("Box A", "sensor.h", 45, 5)
    assert entry.runtime_data.manager.alert_settings.targets == ["notify.me"]  # now one setting for all
    assert entry.runtime_data.manager.alert_settings.persistent is True
    assert manager.boxes[box_b_id].name == "Box B"
    one, two, three = (manager.spools[sid] for sid in ("spool1", "spool2", "spool3"))
    assert (one.box_id, three.box_id) == (box_a_id, box_b_id)
    assert (one.name, one.material, one.manufacturer, one.total_weight) == ("Spool One", "PLA", "Elegoo", 1000)
    assert (one.ams_slot, one.cloud_spool, one.low_stock_threshold) == (SLOT, "11", 20)
    assert two.material == "Nylon"

    # The remaining weight comes from the restored state, else from the initial value.
    assert float(hass.states.get("number.spool_one_remaining_weight").state) == 321
    assert float(hass.states.get("number.spool_two_remaining_weight").state) == 900

    # Entities and devices are the same objects as before, now owned by the one entry.
    assert ent_reg.async_get("number.spool_one_remaining_weight").config_entry_id == entry.entry_id
    assert ent_reg.async_get("number.spool_one_remaining_weight").config_subentry_id is None
    assert device_id(hass, entry, "spool1") == spool_device
    assert hass.states.get("binary_sensor.spool_one_low_stock_alert") is not None
    assert hass.states.get("binary_sensor.spool_one_in_printer").state == "on"  # the learned RFID came along
    assert hass.states.get("binary_sensor.box_a_humidity_alert").state == "off"
    assert hass.states.get("sensor.box_a_spools").state == "2"
    assert hass.states.get("sensor.box_b_spools").state == "1"
    spool_dev = dev_reg.async_get(spool_device)
    assert spool_dev.via_device_id == device_id(hass, entry, box_a_id)

    # What is an attribute now is gone as an entity.
    for gone in ("sensor.spool_one_remaining", "sensor.spool_one_material", "sensor.spool_one_color"):
        assert ent_reg.async_get(gone) is None
        assert hass.states.get(gone) is None
    assert hass.states.get("number.spool_one_remaining_weight").attributes["material"] == "PLA"


async def test_nothing_happens_without_old_entries_and_a_second_start_changes_nothing(
    hass: HomeAssistant, hass_storage
) -> None:
    _legacy_hub(hass, "Box A", [_spool("spool1", "Spool One")])
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.state.value == "loaded"
    assert set(entry.runtime_data.manager.spools) == {"spool1"}
    assert hass.states.get("number.spool_one_remaining_weight") is not None


async def test_a_cloud_account_entry_survives_the_migration(hass: HomeAssistant) -> None:
    from unittest.mock import patch

    from custom_components.ha_filament_manager.cloud import BambuCloudClient

    cloud = MockConfigEntry(
        domain=DOMAIN,
        unique_id="cloud-global-me@example.com",
        data={"cloud": True, "region": "global", "email": "me@example.com", "token": "t"},
    )  # version 1, as 0.14 created it
    cloud.add_to_hass(hass)
    _legacy_hub(hass, "Box A", [_spool("spool1", "Spool One")])
    with patch.object(BambuCloudClient, "get_spools", return_value=[]):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
    assert cloud.state.value == "loaded"
    assert cloud.version == 2
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2
