"""The Filament Manager integration.

A config entry is a hub, and a hub is one filament box (or shelf): its data
holds the box's humidity sensor, limits and notification settings (see
config_flow.py). Every filament spool is a config subentry of a hub, each
getting its own device (linked to the hub's device) and entities. A spool's
live state (remaining weight) is kept in ``entry.runtime_data``, keyed by
its subentry id, so it can be shared between the editable number entity and
the read-only percentage sensor without re-deriving it from entity state
lookups.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .boxes import box_subentry, box_title, new_box_subentry
from .entity import box_device_info
from .const import (
    CARD_FILENAME,
    CARD_URL_PATH,
    CARD_VERSION,
    CONF_INITIAL_REMAINING_WEIGHT,
    CONF_TOTAL_WEIGHT,
    SUBENTRY_TYPE_SPOOL,
)

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR, Platform.BINARY_SENSOR]


@dataclass
class SpoolRuntimeData:
    """Live, mutable state for a single spool."""

    remaining_weight: float


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled Lovelace overview card and register it with the frontend.

    Runs once for the whole integration (unlike async_setup_entry, which runs
    for each hub entry), so the card is available even before the hub is set up.
    """
    card_path = Path(__file__).parent / "www" / CARD_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_PATH, str(card_path), cache_headers=True)]
    )
    add_extra_js_url(hass, f"{CARD_URL_PATH}?v={CARD_VERSION}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the hub (box) entry and every spool subentry it currently holds."""
    # The box subentry owns the hub's device and entities. Hubs from before it
    # existed (or one the user removed) get it back here.
    box = box_subentry(entry)
    if box is None:
        box = new_box_subentry(entry.title)
        hass.config_entries.async_add_subentry(entry, box)
    elif box.title != box_title(entry.title):
        # Named by an earlier version (no sort-first symbol): rename it.
        hass.config_entries.async_update_subentry(entry, box, title=box_title(entry.title))

    # Create the hub's device up front, so every spool's `via_device` link
    # resolves no matter which platform adds its entities first.
    info = box_device_info(entry)
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=box.subentry_id,
        identifiers=info["identifiers"],
        name=info["name"],
        manufacturer=info["manufacturer"],
        model=info["model"],
    )
    if None in device.config_entries_subentries.get(entry.entry_id, set()):
        # Registered on the entry itself by an earlier version: move it under the box.
        dev_reg.async_update_device(
            device.id, remove_config_entry_id=entry.entry_id, remove_config_subentry_id=None
        )

    entry.runtime_data = {
        subentry_id: SpoolRuntimeData(
            remaining_weight=subentry.data.get(
                CONF_INITIAL_REMAINING_WEIGHT, subentry.data[CONF_TOTAL_WEIGHT]
            )
        )
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == SUBENTRY_TYPE_SPOOL
    }
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry whenever a spool subentry is added, edited or removed.

    The box subentry is named like its hub (see box_title), so a rename of the hub (reconfigure
    or the rename dialog) is mirrored onto it first; that update calls this
    listener again, which then reloads.
    """
    box = box_subentry(entry)
    if box is not None and box.title != box_title(entry.title):
        hass.config_entries.async_update_subentry(entry, box, title=box_title(entry.title))
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the hub's config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
