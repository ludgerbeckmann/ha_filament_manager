"""Shared helpers for grouping spool subentries into filament box subentries."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry

from .const import CONF_BOX, SUBENTRY_TYPE_BOX, SUBENTRY_TYPE_SPOOL


def box_subentries(entry: ConfigEntry) -> list[ConfigSubentry]:
    """Return all filament box subentries of the hub entry."""
    return [
        subentry for subentry in entry.subentries.values() if subentry.subentry_type == SUBENTRY_TYPE_BOX
    ]


def spools_in_box(
    entry: ConfigEntry, box_subentry_id: str, *, exclude_subentry_id: str | None = None
) -> list[ConfigSubentry]:
    """Return the spool subentries currently assigned to the given box."""
    return [
        subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_SPOOL
        and subentry.data.get(CONF_BOX) == box_subentry_id
        and subentry.subentry_id != exclude_subentry_id
    ]
