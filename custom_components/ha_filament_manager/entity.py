"""Devices and entity bookkeeping shared by the platforms.

Every box is a device, and every spool *in a box* is a device linked to its
box's device (sealed spools have none). The devices are kept in step with the
inventory here, before the platforms add or remove their entities.
"""
from __future__ import annotations

from collections.abc import Callable
import inspect

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .store import FilamentManager

STOCK_ID = "stock"

# Home Assistant 2026.8 introduced via_device_id (the registry id of the parent
# device) and deprecated the identifier-based via_device.
_HAS_VIA_DEVICE_ID = "via_device_id" in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters


def device_info(device_id: str) -> DeviceInfo:
    """Identify a device of this integration (box, spool or the stock) for an entity."""
    return DeviceInfo(identifiers={(DOMAIN, device_id)})


def _find_device(registry: dr.DeviceRegistry, entry: ConfigEntry, device_id: str) -> dr.DeviceEntry | None:
    identifier = (DOMAIN, device_id)
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(identifier, entry.entry_id)
    return registry.async_get_device(identifiers={identifier})  # Home Assistant before 2026.8


@callback
def async_sync_devices(hass: HomeAssistant, entry: ConfigEntry, manager: FilamentManager) -> None:
    """Create/update the devices of boxes and spools and remove those that are gone."""
    registry = dr.async_get(hass)
    wanted: set[str] = {STOCK_ID}

    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, STOCK_ID)},
        name="Vorrat",
        manufacturer="Filament Manager",
        model="Vorrat",
    )
    box_devices: dict[str, str] = {}
    for box in manager.boxes.values():
        wanted.add(box.id)
        device = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, box.id)},
            name=box.name,
            manufacturer="Filament Manager",
            model="Filamentbox",
        )
        box_devices[box.id] = device.id

    for spool in manager.spools.values():
        if spool.sealed or spool.box_id not in box_devices:
            continue
        wanted.add(spool.id)
        link = (
            {"via_device_id": box_devices[spool.box_id]}
            if _HAS_VIA_DEVICE_ID
            else {"via_device": (DOMAIN, spool.box_id)}
        )
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, spool.id)},
            name=spool.name,
            manufacturer=spool.manufacturer or "Filament Manager",
            model=f"{spool.material} {spool.variant}".strip(),
            **link,
        )

    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        owned = {value for domain, value in device.identifiers if domain == DOMAIN}
        if owned and not owned & wanted:
            registry.async_remove_device(device.id)


class EntitySync:
    """Adds and removes a platform's entities as the inventory changes.

    `wanted()` returns {unique_id: factory}; entities that are no longer wanted
    are removed from the registry (their device may stay), new ones are added.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        domain: str,
        add_entities: AddEntitiesCallback,
        wanted: Callable[[], dict[str, Callable[[], Entity]]],
    ) -> None:
        self._hass = hass
        self._domain = domain
        self._add_entities = add_entities
        self._wanted = wanted
        self._present: set[str] = set()

    @callback
    def __call__(self) -> None:
        wanted = self._wanted()
        new = [factory() for unique_id, factory in wanted.items() if unique_id not in self._present]
        if new:
            self._add_entities(new)
            self._present |= {entity.unique_id for entity in new}
        registry = er.async_get(self._hass)
        for unique_id in self._present - set(wanted):
            if (entity_id := registry.async_get_entity_id(self._domain, DOMAIN, unique_id)) is not None:
                registry.async_remove(entity_id)
            self._present.discard(unique_id)
