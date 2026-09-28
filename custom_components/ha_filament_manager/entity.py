"""Shared helpers for Filament Manager entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_BOX, CONF_MANUFACTURER, CONF_MATERIAL, DOMAIN


def spool_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the device info shared by all entities that belong to one spool."""
    info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=entry.options.get(CONF_MANUFACTURER) or "Filament Manager",
        model=entry.options.get(CONF_MATERIAL),
    )
    box_entry_id = entry.options.get(CONF_BOX)
    if box_entry_id:
        # Links the spool's device to its filament box in the device
        # registry, so HA (and the overview card) can group them - even if
        # the referenced box was since removed, this is silently ignored.
        info["via_device"] = (DOMAIN, box_entry_id)
    return info


def box_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the device info shared by all entities that belong to one filament box."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Filament Manager",
        model="Filamentbox",
    )
