"""Helpers shared by the tests."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_filament_manager.const import CONF_MAIN, DOMAIN
from custom_components.ha_filament_manager.runtime import FilamentRuntime
from custom_components.ha_filament_manager.store import FilamentManager

BOX = "Test Box"
SPOOL = "Test Spool"
NUMBER = "number.test_spool_remaining_weight"


async def setup_inventory(hass: HomeAssistant) -> tuple[MockConfigEntry, FilamentRuntime]:
    """Set up the (empty) Filament Manager entry."""
    entry = MockConfigEntry(domain=DOMAIN, title="Filament Manager", unique_id="main", version=2, data={CONF_MAIN: True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, entry.runtime_data


async def setup_with_spool(
    hass: HomeAssistant, *, box: dict | None = None, spool: dict | None = None
) -> tuple[MockConfigEntry, FilamentManager]:
    """An inventory with one box ("Test Box") holding one spool ("Test Spool")."""
    entry, runtime = await setup_inventory(hass)
    manager = runtime.manager
    new_box = manager.add_box(BOX, **(box or {}))
    manager.add_spool(
        name=SPOOL,
        material="PLA",
        color="Schwarz",
        manufacturer="Elegoo",
        box_id=new_box.id,
        total_weight=1000,
        remaining_weight=750,
        **(spool or {}),
    )
    await hass.async_block_till_done()
    return entry, manager


def device_id(hass: HomeAssistant, entry: MockConfigEntry, identifier: str) -> str:
    """The registry id of a box's or spool's device."""
    registry = dr.async_get(hass)
    identifiers = (DOMAIN, identifier)
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(identifiers, entry.entry_id).id
    return registry.async_get_device(identifiers={identifiers}).id
