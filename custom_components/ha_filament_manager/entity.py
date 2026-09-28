"""Shared helpers for Filament Manager entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_BOX, CONF_MANUFACTURER, CONF_MATERIAL, DOMAIN


def spool_device_info(subentry: ConfigSubentry) -> DeviceInfo:
    """Return the device info shared by all entities that belong to one spool."""
    info = DeviceInfo(
        identifiers={(DOMAIN, subentry.subentry_id)},
        name=subentry.title,
        manufacturer=subentry.data.get(CONF_MANUFACTURER) or "Filament Manager",
        model=subentry.data.get(CONF_MATERIAL),
    )
    box_subentry_id = subentry.data.get(CONF_BOX)
    if box_subentry_id:
        # Links the spool's device to its filament box in the device
        # registry, so HA (and the overview card) can group them - even if
        # the referenced box was since removed, this is silently ignored.
        info["via_device"] = (DOMAIN, box_subentry_id)
    return info


def box_device_info(subentry: ConfigSubentry) -> DeviceInfo:
    """Return the device info shared by all entities that belong to one filament box."""
    return DeviceInfo(
        identifiers={(DOMAIN, subentry.subentry_id)},
        name=subentry.title,
        manufacturer="Filament Manager",
        model="Filamentbox",
    )
