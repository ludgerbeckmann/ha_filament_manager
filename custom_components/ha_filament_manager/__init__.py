"""The Filament Manager integration.

One config entry holds the whole inventory: filament boxes and spools, kept in
a storage file (store.py) and managed from the dashboard card or the services.
Boxes and spools in a box get devices and a few entities that mirror the
inventory; sealed spools (the stock) are just data. Optionally a Bambu cloud
account is a second entry (see cloud.py); it only feeds remaining weights.
"""
from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .ams import AmsTracker
from .cloud import CloudCoordinator, CloudRuntimeData, async_announce_updates, is_cloud_entry
from .cloud_sync import CloudSync
from .const import CARD_FILENAME, CARD_URL_PATH, CARD_VERSION, SIGNAL_SNAPSHOT_DIRTY
from .entity import async_sync_devices
from .manage import async_register_services
from .migrate import CURRENT_VERSION, async_migrate_legacy
from .runtime import FilamentRuntime
from .store import FilamentManager
from .websocket import async_register_websocket

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard card, register services and websocket commands, migrate old data.

    Runs once for the whole integration, before any entry is set up - which is
    why the migration of the old one-entry-per-box layout lives here.
    """
    card_path = Path(__file__).parent / "www" / CARD_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL_PATH, str(card_path), cache_headers=True)]
    )
    add_extra_js_url(hass, f"{CARD_URL_PATH}?v={CARD_VERSION}")
    async_register_services(hass)
    async_register_websocket(hass)
    await async_migrate_legacy(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Entries left on an old version have nothing to convert (box entries were handled in async_setup)."""
    if entry.version < CURRENT_VERSION:
        hass.config_entries.async_update_entry(entry, version=CURRENT_VERSION)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the inventory (or the cloud account)."""
    if is_cloud_entry(entry):
        return await _async_setup_cloud_entry(hass, entry)

    manager = FilamentManager(hass)
    await manager.async_load()
    ams = AmsTracker(hass, manager)
    cloud = CloudSync(hass, manager, ams)
    runtime = FilamentRuntime(manager, ams, cloud)
    entry.runtime_data = runtime

    async_sync_devices(hass, entry, manager)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Only follow the AMS and the cloud once the entities exist to receive their updates.
    await ams.async_start()
    await cloud.async_start()

    def _changed(structure: bool) -> None:
        if not structure:
            return
        async_sync_devices(hass, entry, manager)
        for sync in runtime.syncers:
            sync()
        ams.reconfigure()
        cloud.reconfigure()
        # Entity ids of new entities are only known now.
        async_dispatcher_send(hass, SIGNAL_SNAPSHOT_DIRTY)

    entry.async_on_unload(manager.async_add_listener(_changed))
    entry.async_on_unload(ams.async_stop)
    entry.async_on_unload(cloud.async_stop)
    entry.async_on_unload(manager.async_flush)  # a change of the last second must not be lost
    return True


async def _async_setup_cloud_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Bambu cloud account: it only feeds the spools, it has no entities."""
    coordinator = CloudCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = CloudRuntimeData(coordinator)
    async_announce_updates(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the inventory (or the cloud account)."""
    if is_cloud_entry(entry):
        return True
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
