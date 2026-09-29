"""Shared helpers for grouping spool subentries into filament box subentries."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry

from .const import (
    CONF_BOX,
    CONF_HUMIDITY_DELAY,
    CONF_HUMIDITY_MAX,
    CONF_MATERIAL,
    DEFAULT_HUMIDITY_DELAY,
    DEFAULT_HUMIDITY_MAX,
    SUBENTRY_TYPE_BOX,
    SUBENTRY_TYPE_SPOOL,
    suggested_humidity_delay,
    suggested_humidity_max,
)


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


def effective_box_humidity_limits(entry: ConfigEntry, box: ConfigSubentry) -> tuple[float, float]:
    """Return a box's (max humidity %, alert delay in minutes).

    Values set explicitly on the box always win. Fields left empty are
    automatic: the strictest suggestion of any material stored in the box
    (lowest humidity limit, shortest delay), so the most sensitive spool
    decides. An empty box falls back to the generic defaults.
    """
    materials = [spool.data.get(CONF_MATERIAL) for spool in spools_in_box(entry, box.subentry_id)]

    if (threshold := box.data.get(CONF_HUMIDITY_MAX)) is None:
        threshold = min((suggested_humidity_max(m) for m in materials), default=DEFAULT_HUMIDITY_MAX)
    if (delay := box.data.get(CONF_HUMIDITY_DELAY)) is None:
        delay = min((suggested_humidity_delay(m) for m in materials), default=DEFAULT_HUMIDITY_DELAY)

    return threshold, delay
