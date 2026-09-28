"""The Filament Manager integration.

Each config entry represents exactly one filament spool. Its live state
(remaining weight) is kept in ``entry.runtime_data`` so it can be shared
between the editable number entity and the read-only percentage sensor
without re-deriving it from entity state lookups.
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
)

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR, Platform.BINARY_SENSOR]


@dataclass
class SpoolRuntimeData:
    """Live, mutable state for a single spool."""

    remaining_weight: float


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled Lovelace overview card and register it with the frontend.

    Runs once for the whole integration (unlike async_setup_entry, which runs
    per spool), so the card is available even before any spool is configured.
    """
    card_path = Path(__file__).parent / "www" / CARD_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_PATH, str(card_path), cache_headers=True)]
    )
    add_extra_js_url(hass, f"{CARD_URL_PATH}?v={CARD_VERSION}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a spool from a config entry."""
    entry.runtime_data = SpoolRuntimeData(
        remaining_weight=entry.options.get(
            CONF_INITIAL_REMAINING_WEIGHT, entry.options[CONF_TOTAL_WEIGHT]
        )
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options are edited."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a spool's config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
