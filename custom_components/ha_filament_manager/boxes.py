"""Shared helpers for grouping spools into filament boxes."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_BOX, CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_BOX, ENTRY_TYPE_SPOOL


def box_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return all configured filament box entries."""
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_BOX
    ]


def spools_in_box(
    hass: HomeAssistant, box_entry_id: str, *, exclude_entry_id: str | None = None
) -> list[ConfigEntry]:
    """Return the spool entries currently assigned to the given box."""
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_SPOOL) == ENTRY_TYPE_SPOOL
        and entry.options.get(CONF_BOX) == box_entry_id
        and entry.entry_id != exclude_entry_id
    ]
