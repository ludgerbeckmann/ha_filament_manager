"""The Filament Manager integration.

A config entry is a hub (several can exist, e.g. one per filament box).
Every filament spool and filament box is a config subentry of a hub (see
boxes.py and config_flow.py), each still getting its own device and
entities. A spool's live state (remaining weight) is kept in
``entry.runtime_data``, keyed by its subentry id, so it can be shared between
the editable number entity and the read-only percentage sensor without
re-deriving it from entity state lookups.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

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
    """Set up the hub entry and every spool/box subentry it currently holds."""
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
    """Reload the entry whenever a spool/box subentry is added, edited or removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the hub's config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
