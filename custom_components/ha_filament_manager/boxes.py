"""Helpers for a hub's (= filament box's) spools and humidity limits."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry

from .const import (
    CONF_HUMIDITY_DELAY,
    CONF_HUMIDITY_MAX,
    CONF_MATERIAL,
    DEFAULT_HUMIDITY_DELAY,
    DEFAULT_HUMIDITY_MAX,
    SUBENTRY_TYPE_SPOOL,
    suggested_humidity_delay,
    suggested_humidity_max,
)


def spool_subentries(entry: ConfigEntry, *, exclude_subentry_id: str | None = None) -> list[ConfigSubentry]:
    """Return the spool subentries of a hub."""
    return [
        subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_SPOOL and subentry.subentry_id != exclude_subentry_id
    ]


def effective_box_humidity_limits(entry: ConfigEntry) -> tuple[float, float]:
    """Return a hub's (max humidity %, alert delay in minutes).

    Values set explicitly on the hub always win. Fields left empty are
    automatic: the strictest suggestion of any material stored in the hub
    (lowest humidity limit, shortest delay), so the most sensitive spool
    decides. An empty hub falls back to the generic defaults.
    """
    materials = [spool.data.get(CONF_MATERIAL) for spool in spool_subentries(entry)]

    if (threshold := entry.data.get(CONF_HUMIDITY_MAX)) is None:
        threshold = min((suggested_humidity_max(m) for m in materials), default=DEFAULT_HUMIDITY_MAX)
    if (delay := entry.data.get(CONF_HUMIDITY_DELAY)) is None:
        delay = min((suggested_humidity_delay(m) for m in materials), default=DEFAULT_HUMIDITY_DELAY)

    return threshold, delay
