"""Sensor platform for Filament Manager: how many spools a box holds, and the stock."""
from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SIGNAL_SNAPSHOT_DIRTY, signal_box_updated
from .entity import STOCK_ID, EntitySync, device_info
from .runtime import FilamentRuntime


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up a spool counter per box and one for the sealed spools."""
    runtime: FilamentRuntime = entry.runtime_data

    def wanted() -> dict[str, Any]:
        found: dict[str, Any] = {
            f"{box_id}_spool_count": (lambda box_id=box_id: FilamentBoxSpoolCountSensor(runtime, box_id))
            for box_id in runtime.manager.boxes
        }
        found["stock_count"] = lambda: FilamentStockSensor(runtime)
        return found

    sync = EntitySync(hass, "sensor", async_add_entities, wanted)
    runtime.syncers.append(sync)
    sync()


class FilamentBoxSpoolCountSensor(SensorEntity):
    """How many spools are stored in this box."""

    _attr_has_entity_name = True
    _attr_translation_key = "spool_count"
    _attr_icon = "mdi:tray-full"
    _attr_should_poll = False

    def __init__(self, runtime: FilamentRuntime, box_id: str) -> None:
        self._manager = runtime.manager
        self._box_id = box_id
        self._attr_unique_id = f"{box_id}_spool_count"
        self._attr_device_info = device_info(box_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_box_updated(self._box_id), self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        if self._box_id in self._manager.boxes:
            self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        return len(self._manager.spools_in(self._box_id)) if self._box_id in self._manager.boxes else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        box = self._manager.boxes.get(self._box_id)
        return {"spool_limit": box.spool_limit, "box_id": box.id} if box else None


class FilamentStockSensor(SensorEntity):
    """How many sealed spools are in the stock (Vorrat)."""

    _attr_has_entity_name = True
    _attr_translation_key = "stock_count"
    _attr_icon = "mdi:package-variant-closed"
    _attr_should_poll = False

    def __init__(self, runtime: FilamentRuntime) -> None:
        self._manager = runtime.manager
        self._attr_unique_id = "stock_count"
        self._attr_device_info = device_info(STOCK_ID)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_SNAPSHOT_DIRTY, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return len(self._manager.stock())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"by_material": dict(Counter(spool.material for spool in self._manager.stock()))}
