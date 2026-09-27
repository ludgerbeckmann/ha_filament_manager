"""Binary sensor platform for Filament Manager: humidity monitoring.

Only created when a spool has an (optional) humidity sensor configured. It
tracks that external sensor's state and turns on when the humidity exceeds
the configured threshold, e.g. for an opened spool stored outside a dry box.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_HUMIDITY_MAX, CONF_HUMIDITY_SENSOR, DEFAULT_HUMIDITY_MAX
from .entity import spool_device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the humidity alert binary sensor, if a humidity sensor is configured."""
    humidity_sensor = entry.options.get(CONF_HUMIDITY_SENSOR)
    if not humidity_sensor:
        return
    async_add_entities([FilamentHumidityAlert(entry, humidity_sensor)])


class FilamentHumidityAlert(BinarySensorEntity):
    """Warns when the monitored humidity for an opened spool is too high."""

    _attr_has_entity_name = True
    _attr_translation_key = "humidity_alert"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_icon = "mdi:water-percent"

    def __init__(self, entry: ConfigEntry, source_entity_id: str) -> None:
        self._source_entity_id = source_entity_id
        self._threshold = entry.options.get(CONF_HUMIDITY_MAX, DEFAULT_HUMIDITY_MAX)
        self._current_humidity: float | None = None
        self._attr_unique_id = f"{entry.entry_id}_humidity_alert"
        self._attr_device_info = spool_device_info(entry)
        self._attr_available = False
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Start tracking the referenced humidity sensor."""
        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._source_entity_id], self._handle_source_event)
        )
        if (state := self.hass.states.get(self._source_entity_id)) is not None:
            self._update_from_state(state.state)

    @callback
    def _handle_source_event(self, event: Event) -> None:
        new_state = event.data["new_state"]
        self._update_from_state(new_state.state if new_state else None)
        self.async_write_ha_state()

    def _update_from_state(self, raw_state: str | None) -> None:
        try:
            self._current_humidity = float(raw_state)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            self._current_humidity = None
            self._attr_available = False
            self._attr_is_on = False
            return
        self._attr_available = True
        self._attr_is_on = self._current_humidity > self._threshold

    @property
    def extra_state_attributes(self) -> dict[str, float | str | None]:
        """Return diagnostic attributes for the humidity alert."""
        return {
            "current_humidity": self._current_humidity,
            "threshold": self._threshold,
            "source_entity_id": self._source_entity_id,
        }
