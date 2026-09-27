"""Sensor platform for Filament Manager: percentage, material and color."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_COLOR,
    CONF_DIAMETER,
    CONF_MANUFACTURER,
    CONF_MATERIAL,
    CONF_TOTAL_WEIGHT,
    signal_spool_updated,
)
from .entity import spool_device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the read-only spool sensors."""
    async_add_entities(
        [
            FilamentRemainingPercentageSensor(entry),
            FilamentMaterialSensor(entry),
            FilamentColorSensor(entry),
        ]
    )


class FilamentRemainingPercentageSensor(SensorEntity):
    """Remaining filament as a percentage of the spool's total weight."""

    _attr_has_entity_name = True
    _attr_translation_key = "remaining_percentage"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_remaining_percentage"
        self._attr_device_info = spool_device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Recompute whenever the spool's remaining weight changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_spool_updated(self._entry.entry_id), self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        """Return the remaining filament in percent."""
        total = self._entry.options.get(CONF_TOTAL_WEIGHT)
        if not total:
            return None
        remaining = self._entry.runtime_data.remaining_weight
        return round(remaining / total * 100, 1)


class FilamentMaterialSensor(SensorEntity):
    """The material type of the spool (e.g. PLA, PETG)."""

    _attr_has_entity_name = True
    _attr_translation_key = "material"
    _attr_icon = "mdi:flask-outline"

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_material"
        self._attr_device_info = spool_device_info(entry)
        self._attr_native_value = entry.options.get(CONF_MATERIAL)
        self._attr_extra_state_attributes = {
            "diameter_mm": entry.options.get(CONF_DIAMETER),
            "manufacturer": entry.options.get(CONF_MANUFACTURER),
            "total_weight_g": entry.options.get(CONF_TOTAL_WEIGHT),
        }


class FilamentColorSensor(SensorEntity):
    """The color of the spool."""

    _attr_has_entity_name = True
    _attr_translation_key = "color"
    _attr_icon = "mdi:palette"

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_color"
        self._attr_device_info = spool_device_info(entry)
        self._attr_native_value = entry.options.get(CONF_COLOR)
