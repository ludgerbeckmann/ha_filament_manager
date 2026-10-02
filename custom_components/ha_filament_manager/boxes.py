"""Helpers for a hub's (= filament box's) spools and humidity limits."""
from __future__ import annotations

from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigSubentry

from .const import (
    BOX_TITLE_PREFIX,
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


def box_subentry(entry: ConfigEntry) -> ConfigSubentry | None:
    """Return the hub's box subentry (the owner of the box's device and entities), if any."""
    return next(
        (s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_BOX),
        None,
    )


def box_title(hub_title: str) -> str:
    """Return the title of a hub's box subentry: the hub's name behind a sort-first "# ".

    The prefix is always present, whatever the hub's name: it is added when
    missing and never doubled.
    """
    name = hub_title.strip()
    return name if name.startswith(BOX_TITLE_PREFIX) else f"{BOX_TITLE_PREFIX}{name}"


def new_box_subentry(hub_title: str) -> ConfigSubentry:
    """Build the box subentry a hub needs, named like the hub."""
    return ConfigSubentry(
        data=MappingProxyType({}),
        subentry_type=SUBENTRY_TYPE_BOX,
        title=box_title(hub_title),
        unique_id=None,
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
