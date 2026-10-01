"""Number platform for Filament Manager.

The remaining weight of a spool is modelled as an editable number entity so
it can be adjusted directly from a dashboard, in addition to the
``consume_filament`` / ``refill_spool`` services meant for automations.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components.number import NumberDeviceClass, NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_AMOUNT,
    CONF_INITIAL_REMAINING_WEIGHT,
    CONF_TOTAL_WEIGHT,
    SERVICE_CONSUME_FILAMENT,
    SERVICE_REFILL_SPOOL,
    SUBENTRY_TYPE_SPOOL,
    signal_spool_updated,
)
from .entity import spool_device_info

CONSUME_SCHEMA = {vol.Required(ATTR_AMOUNT): vol.All(vol.Coerce(float), vol.Range(min=0.01))}
REFILL_SCHEMA = {vol.Optional(ATTR_AMOUNT): vol.All(vol.Coerce(float), vol.Range(min=0))}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the remaining-weight number entity and its services for every spool."""
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_CONSUME_FILAMENT, CONSUME_SCHEMA, "async_consume")
    platform.async_register_entity_service(SERVICE_REFILL_SPOOL, REFILL_SCHEMA, "async_refill")

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_SPOOL:
            continue
        async_add_entities(
            [FilamentRemainingWeightNumber(entry, subentry)], config_subentry_id=subentry_id
        )


class FilamentRemainingWeightNumber(RestoreNumber):
    """The editable, persisted remaining weight of a filament spool."""

    _attr_has_entity_name = True
    _attr_translation_key = "remaining_weight"
    _attr_native_unit_of_measurement = UnitOfMass.GRAMS
    _attr_device_class = NumberDeviceClass.WEIGHT
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_icon = "mdi:printer-3d-nozzle-outline"

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        self._entry = entry
        self._subentry = subentry
        self._attr_unique_id = f"{subentry.subentry_id}_remaining_weight"
        self._attr_device_info = spool_device_info(entry, subentry)
        self._attr_native_max_value = subentry.data[CONF_TOTAL_WEIGHT]

    async def async_added_to_hass(self) -> None:
        """Restore the last known remaining weight, falling back to the configured initial value."""
        await super().async_added_to_hass()

        restored_value: float | None = None
        if (last_number_data := await self.async_get_last_number_data()) is not None:
            restored_value = last_number_data.native_value
        if restored_value is None:
            restored_value = self._subentry.data.get(CONF_INITIAL_REMAINING_WEIGHT, self._attr_native_max_value)

        self._attr_native_value = max(0, min(restored_value, self._attr_native_max_value))
        self._entry.runtime_data[self._subentry.subentry_id].remaining_weight = self._attr_native_value
        async_dispatcher_send(self.hass, signal_spool_updated(self._subentry.subentry_id))

    async def async_set_native_value(self, value: float) -> None:
        """Update the remaining weight."""
        self._attr_native_value = max(0, min(value, self._attr_native_max_value))
        self._entry.runtime_data[self._subentry.subentry_id].remaining_weight = self._attr_native_value
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, signal_spool_updated(self._subentry.subentry_id))

    async def async_consume(self, amount: float) -> None:
        """Subtract the given amount of used filament, in grams."""
        await self.async_set_native_value((self._attr_native_value or 0) - amount)

    async def async_refill(self, amount: float | None = None) -> None:
        """Reset the remaining weight, e.g. after mounting a fresh spool."""
        target = amount if amount is not None else self._attr_native_max_value
        await self.async_set_native_value(target)
