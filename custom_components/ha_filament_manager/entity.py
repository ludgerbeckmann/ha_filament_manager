"""Shared helpers for Filament Manager entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_MANUFACTURER, CONF_MATERIAL, DOMAIN


def box_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the device info of a hub - the filament box all its spools belong to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Filament Manager",
        model="Filamentbox",
    )


def spool_device_info(entry: ConfigEntry, subentry: ConfigSubentry) -> DeviceInfo:
    """Return the device info shared by all entities that belong to one spool.

    The spool's device is linked to its hub's (box) device, so Home Assistant
    and the overview card can group them.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, subentry.subentry_id)},
        name=subentry.title,
        manufacturer=subentry.data.get(CONF_MANUFACTURER) or "Filament Manager",
        model=subentry.data.get(CONF_MATERIAL),
        via_device=(DOMAIN, entry.entry_id),
    )
