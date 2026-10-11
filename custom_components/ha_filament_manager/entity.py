"""Shared helpers for Filament Manager entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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


def hub_device_id(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Return the registry id of the hub's (box) device, if it exists yet."""
    registry = dr.async_get(hass)
    identifier = (DOMAIN, entry.entry_id)
    if hasattr(registry, "async_get_device_by_identifier"):
        device = registry.async_get_device_by_identifier(identifier, entry.entry_id)
    else:  # Home Assistant before 2026.8
        device = registry.async_get_device(identifiers={identifier})
    return device.id if device is not None else None


def spool_device_info(hass: HomeAssistant, entry: ConfigEntry, subentry: ConfigSubentry) -> DeviceInfo:
    """Return the device info shared by all entities that belong to one spool.

    The spool's device is linked to its hub's (box) device, so Home Assistant
    and the overview card can group them. Home Assistant 2026.8 deprecated the
    identifier-based `via_device` (removal: 2027.8) in favour of `via_device_id`,
    the registry id of the parent device; older versions only know `via_device`.
    """
    info = DeviceInfo(
        identifiers={(DOMAIN, subentry.subentry_id)},
        name=subentry.title,
        manufacturer=subentry.data.get(CONF_MANUFACTURER) or "Filament Manager",
        model=subentry.data.get(CONF_MATERIAL),
    )
    if "via_device_id" in DeviceInfo.__annotations__:
        if (hub_id := hub_device_id(hass, entry)) is not None:
            info["via_device_id"] = hub_id
    else:
        info["via_device"] = (DOMAIN, entry.entry_id)
    return info
