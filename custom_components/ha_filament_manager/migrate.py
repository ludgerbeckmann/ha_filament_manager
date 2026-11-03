"""Bring the data of versions before 1.0 into the inventory.

Until then every box was a config entry and every spool a subentry of it,
with the remaining weight kept as the restored state of the number entity.
Now there is one entry and the inventory lives in a storage file (store.py).

The ids are carried over - a box keeps its former entry id, a spool its
subentry id - so the unique ids of the entities and the identifiers of the
devices stay valid: devices and entities are re-pointed at the one entry, and
entity ids, names, history and areas survive. The read-only sensors that no
longer exist (percentage, material, color: now attributes of the remaining
weight) are dropped.

This runs once at start-up, before any entry is set up.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.helpers.storage import Store

from .cloud import is_cloud_entry
from .const import (
    CONF_AMS_SLOT,
    CONF_AMS_SYNC,
    CONF_CLOUD_SPOOL,
    CONF_CLOUD_SYNC,
    CONF_COLOR,
    CONF_DIAMETER,
    CONF_HUMIDITY_DELAY,
    CONF_HUMIDITY_MAX,
    CONF_HUMIDITY_SENSOR,
    CONF_INITIAL_REMAINING_WEIGHT,
    CONF_LOW_STOCK_THRESHOLD,
    CONF_MAIN,
    CONF_MANUFACTURER,
    CONF_MATERIAL,
    CONF_NOTIFY_TARGETS,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_SPOOL_LIMIT,
    CONF_TOTAL_WEIGHT,
    DEFAULT_TOTAL_WEIGHT,
    DOMAIN,
    SUBENTRY_TYPE_SPOOL,
)
from .store import Box, FilamentManager, Spool

_LOGGER = logging.getLogger(__name__)

MAIN_UNIQUE_ID = "main"
CURRENT_VERSION = 2

# Entities of the old model that are attributes of the remaining weight now.
_OBSOLETE_SUFFIXES = ("_remaining_percentage", "_material", "_color")
# A spool's own humidity alert (superseded by its box's, long before 1.0).
_SPOOL_HUMIDITY_SUFFIX = "_humidity_alert"

_MOVES_DEVICES = "new_config_entry_id" in inspect.signature(dr.DeviceRegistry.async_update_device).parameters


def _restored_remaining(hass: HomeAssistant, ent_reg: er.EntityRegistry, spool_id: str) -> float | None:
    entity_id = ent_reg.async_get_entity_id("number", DOMAIN, f"{spool_id}_remaining_weight")
    stored = restore_state.async_get(hass).last_states.get(entity_id) if entity_id else None
    if stored is None or stored.state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    try:
        return float(stored.state.state)
    except ValueError:
        return None


async def async_migrate_legacy(hass: HomeAssistant) -> None:
    """Convert box entries with spool subentries into the one inventory entry."""
    legacy = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.version < CURRENT_VERSION and not is_cloud_entry(entry)
    ]
    if not legacy:
        return
    _LOGGER.info("Migrating %s filament box entries to the Filament Manager inventory", len(legacy))

    ent_reg = er.async_get(hass)
    manager = FilamentManager(hass)
    await manager.async_load()
    spool_ids: set[str] = set()
    ams_records: dict[str, Any] = {}
    cloud_records: dict[str, Any] = {}
    old_stores: list[Store] = []

    for entry in legacy:
        data = entry.data
        manager.boxes[entry.entry_id] = Box(
            id=entry.entry_id,
            name=entry.title,
            humidity_sensor=data.get(CONF_HUMIDITY_SENSOR) or None,
            humidity_max=data.get(CONF_HUMIDITY_MAX),
            humidity_delay=data.get(CONF_HUMIDITY_DELAY),
            spool_limit=data.get(CONF_SPOOL_LIMIT) or None,
        )
        _collect_alerts(manager, data)
        for subentry in entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_SPOOL:
                continue
            spool_data = subentry.data
            _collect_alerts(manager, spool_data)
            total = spool_data.get(CONF_TOTAL_WEIGHT, DEFAULT_TOTAL_WEIGHT)
            remaining = _restored_remaining(hass, ent_reg, subentry.subentry_id)
            if remaining is None:
                remaining = spool_data.get(CONF_INITIAL_REMAINING_WEIGHT, total)
            spool_ids.add(subentry.subentry_id)
            manager.spools[subentry.subentry_id] = Spool(
                id=subentry.subentry_id,
                name=subentry.title,
                material=spool_data.get(CONF_MATERIAL, ""),
                color=spool_data.get(CONF_COLOR, ""),
                manufacturer=spool_data.get(CONF_MANUFACTURER) or "",
                diameter=str(spool_data.get(CONF_DIAMETER, "1.75")),
                total_weight=total,
                remaining_weight=min(remaining, total),
                box_id=entry.entry_id,
                ams_slot=spool_data.get(CONF_AMS_SLOT) or None,
                ams_sync=bool(spool_data.get(CONF_AMS_SYNC, True)),
                cloud_spool=str(spool_data[CONF_CLOUD_SPOOL]) if spool_data.get(CONF_CLOUD_SPOOL) else None,
                cloud_sync=bool(spool_data.get(CONF_CLOUD_SYNC, True)),
                low_stock_threshold=spool_data.get(CONF_LOW_STOCK_THRESHOLD),
            )
        for name, bucket in (("ams", ams_records), ("cloud", cloud_records)):
            store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{name}_{entry.entry_id}")
            if records := await store.async_load():
                bucket.update(records)
            old_stores.append(store)

    # The inventory is on disk before anything of the old model is touched.
    await manager.async_save_now()
    for name, records in (("ams", ams_records), ("cloud", cloud_records)):
        if records:
            store = Store(hass, 1, f"{DOMAIN}.{name}")
            await store.async_save({**(await store.async_load() or {}), **records})

    main = legacy[0]
    for entry in legacy:
        _repoint_registries(hass, entry, main, spool_ids)
    for subentry_id in list(main.subentries):
        hass.config_entries.async_remove_subentry(main, subentry_id)
    hass.config_entries.async_update_entry(
        main, data={CONF_MAIN: True}, title="Filament Manager", unique_id=MAIN_UNIQUE_ID, version=CURRENT_VERSION
    )
    for entry in legacy[1:]:
        await hass.config_entries.async_remove(entry.entry_id)
    for store in old_stores:
        await store.async_remove()


def _collect_alerts(manager: FilamentManager, data: Any) -> None:
    """Targets that boxes and spools used to have each now are the common ones."""
    alerts = manager.alert_settings
    for target in data.get(CONF_NOTIFY_TARGETS) or []:
        if target not in alerts.targets:
            alerts.targets.append(target)
    alerts.persistent = alerts.persistent or bool(data.get(CONF_PERSISTENT_NOTIFICATION))


def _repoint_registries(hass: HomeAssistant, entry: Any, main: Any, spool_ids: set[str]) -> None:
    """Hand the entities and devices of an old box entry to the one entry."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    for entity in list(er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
        unique_id = entity.unique_id or ""
        owner = unique_id.removesuffix(_SPOOL_HUMIDITY_SUFFIX)
        if unique_id.endswith(_OBSOLETE_SUFFIXES) or (
            unique_id.endswith(_SPOOL_HUMIDITY_SUFFIX) and owner in spool_ids
        ):
            ent_reg.async_remove(entity.entity_id)
            continue
        ent_reg.async_update_entity(
            entity.entity_id, config_entry_id=main.entry_id, config_subentry_id=None
        )

    for device in list(dr.async_entries_for_config_entry(dev_reg, entry.entry_id)):
        if _MOVES_DEVICES:
            dev_reg.async_update_device(
                device.id, new_config_entry_id=main.entry_id, new_config_subentry_id=None
            )
            continue
        # Home Assistant before 2026.9: a device may belong to several entries.
        subentries = set(device.config_entries_subentries.get(entry.entry_id) or {None})
        dev_reg.async_update_device(device.id, add_config_entry_id=main.entry_id, add_config_subentry_id=None)
        for subentry_id in subentries:
            if entry.entry_id == main.entry_id and subentry_id is None:
                continue
            dev_reg.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id, remove_config_subentry_id=subentry_id
            )
