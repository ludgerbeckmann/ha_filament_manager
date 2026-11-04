"""Number platform for Filament Manager.

The remaining weight of a spool in a box is an editable number entity, so it
can be adjusted directly from a dashboard, in addition to the
``consume_filament`` / ``refill_spool`` services meant for automations. The
value itself lives in the inventory (store.py); this entity mirrors it and
carries the spool's details as attributes.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_AMOUNT,
    SERVICE_CONSUME_FILAMENT,
    SERVICE_REFILL_SPOOL,
    signal_ams_remaining,
    signal_cloud_matched,
    signal_cloud_remaining,
    signal_spool_updated,
)
from .entity import EntitySync, device_info
from .runtime import FilamentRuntime

CONSUME_SCHEMA = {vol.Required(ATTR_AMOUNT): vol.All(vol.Coerce(float), vol.Range(min=0.01))}
REFILL_SCHEMA = {vol.Optional(ATTR_AMOUNT): vol.All(vol.Coerce(float), vol.Range(min=0))}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up a remaining-weight number for every spool in a box, and the services."""
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_CONSUME_FILAMENT, CONSUME_SCHEMA, "async_consume")
    platform.async_register_entity_service(SERVICE_REFILL_SPOOL, REFILL_SCHEMA, "async_refill")

    runtime: FilamentRuntime = entry.runtime_data

    def wanted() -> dict[str, Any]:
        return {
            f"{spool.id}_remaining_weight": (lambda spool_id=spool.id: FilamentRemainingWeightNumber(runtime, spool_id))
            for spool in runtime.manager.spools.values()
            if not spool.sealed
        }

    sync = EntitySync(hass, "number", async_add_entities, wanted)
    runtime.syncers.append(sync)
    sync()


class FilamentRemainingWeightNumber(NumberEntity):
    """The editable remaining weight of a filament spool."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "remaining_weight"
    _attr_native_unit_of_measurement = UnitOfMass.GRAMS
    _attr_device_class = NumberDeviceClass.WEIGHT
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_icon = "mdi:printer-3d-nozzle-outline"

    def __init__(self, runtime: FilamentRuntime, spool_id: str) -> None:
        self._runtime = runtime
        self._spool_id = spool_id
        self._attr_unique_id = f"{spool_id}_remaining_weight"
        self._attr_device_info = device_info(spool_id)

    @property
    def _spool(self):
        return self._runtime.manager.spools.get(self._spool_id)

    async def async_added_to_hass(self) -> None:
        """Follow the inventory, and the AMS / cloud when the spool is coupled to them."""
        for signal in (
            signal_spool_updated(self._spool_id),
            signal_cloud_matched(self._spool_id),
        ):
            self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._handle_update))
        for signal in (signal_ams_remaining(self._spool_id), signal_cloud_remaining(self._spool_id)):
            self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._handle_percent))

    @callback
    def _handle_update(self) -> None:
        if self._spool is not None:
            self.async_write_ha_state()

    @callback
    def _handle_percent(self, percent: float) -> None:
        """Follow the AMS or the cloud: their percentage refers to this spool's total weight."""
        if (spool := self._spool) is not None:
            self._runtime.manager.set_remaining(self._spool_id, round(spool.total_weight * percent / 100))

    @property
    def available(self) -> bool:
        return self._spool is not None

    @property
    def native_value(self) -> float | None:
        return self._spool.remaining_weight if self._spool else None

    @property
    def native_max_value(self) -> float:
        return self._spool.total_weight if self._spool else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """The spool's details, and the matched Bambu cloud spool when there is one."""
        spool = self._spool
        if spool is None:
            return None
        box = self._runtime.manager.boxes.get(spool.box_id or "")
        attributes: dict[str, Any] = {
            "spool_id": spool.id,
            "material": spool.material,
            "variant": spool.variant,
            "color": spool.color,
            "manufacturer": spool.manufacturer,
            "diameter_mm": spool.diameter,
            "total_weight_g": spool.total_weight,
            "remaining_percentage": round(spool.remaining_weight / spool.total_weight * 100, 1)
            if spool.total_weight
            else None,
            "box": box.name if box else None,
            "box_id": spool.box_id,
            "ams_slot": spool.ams_slot,
        }
        if match := self._runtime.cloud.matches.get(self._spool_id):
            attributes["cloud_spool"] = match.name
            attributes["cloud_spool_id"] = match.id
        return attributes

    async def async_set_native_value(self, value: float) -> None:
        """Update the remaining weight."""
        self._runtime.manager.set_remaining(self._spool_id, value)

    async def async_consume(self, amount: float) -> None:
        """Subtract the given amount of used filament, in grams."""
        if (spool := self._spool) is not None:
            self._runtime.manager.set_remaining(self._spool_id, spool.remaining_weight - amount)

    async def async_refill(self, amount: float | None = None) -> None:
        """Reset the remaining weight, e.g. after mounting a fresh spool."""
        if (spool := self._spool) is None:
            return
        self._runtime.manager.set_remaining(self._spool_id, amount if amount is not None else spool.total_weight)
        # A fresh spool: the RFID learned for the old one no longer applies.
        self._runtime.ams.forget(self._spool_id)
