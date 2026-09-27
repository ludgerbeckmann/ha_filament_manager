"""Shared helpers for Filament Manager entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_MANUFACTURER, CONF_MATERIAL, DOMAIN


def spool_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the device info shared by all entities that belong to one spool."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer=entry.options.get(CONF_MANUFACTURER) or "Filament Manager",
        model=entry.options.get(CONF_MATERIAL),
    )
