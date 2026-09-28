"""Binary sensor platform for Filament Manager: humidity and low-stock alerts.

Both are optional and only created when configured for a spool. Each pushes
a notification (and/or creates a persistent notification) on the off -> on
transition, and clears it again on the on -> off transition - see
notify_helper.py.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BOX,
    CONF_ENTRY_TYPE,
    CONF_HUMIDITY_MAX,
    CONF_HUMIDITY_SENSOR,
    CONF_LOW_STOCK_THRESHOLD,
    CONF_TOTAL_WEIGHT,
    DEFAULT_HUMIDITY_MAX,
    DOMAIN,
    ENTRY_TYPE_BOX,
    signal_spool_updated,
)
from .entity import box_device_info, spool_device_info
from .notify_helper import async_handle_alert_transition


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the humidity and/or low-stock alert binary sensors, if configured."""
    entities: list[BinarySensorEntity] = []

    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_BOX:
        humidity_sensor = entry.options.get(CONF_HUMIDITY_SENSOR)
        if humidity_sensor:
            entities.append(FilamentHumidityAlert(entry, humidity_sensor, device_info=box_device_info(entry)))
    else:
        humidity_sensor = entry.options.get(CONF_HUMIDITY_SENSOR)
        # A spool assigned to a box is monitored by the box's own humidity
        # sensor instead - its own (if still configured) is ignored, and any
        # entity left over from before it was assigned is removed (it would
        # otherwise linger as a stale, "unavailable" registry entry that
        # still shows up on the overview card).
        has_box = bool(entry.options.get(CONF_BOX))
        if humidity_sensor and not has_box:
            entities.append(FilamentHumidityAlert(entry, humidity_sensor, device_info=spool_device_info(entry)))
        elif has_box:
            _async_remove_humidity_alert_entity(hass, entry)

        if entry.options.get(CONF_LOW_STOCK_THRESHOLD) is not None:
            entities.append(FilamentLowStockAlert(entry))

    if entities:
        async_add_entities(entities)


def _async_remove_humidity_alert_entity(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove a spool's own humidity alert entity, now superseded by its box."""
    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_humidity_alert"
    if (entity_id := registry.async_get_entity_id("binary_sensor", DOMAIN, unique_id)) is not None:
        registry.async_remove(entity_id)


class FilamentHumidityAlert(BinarySensorEntity):
    """Warns when the monitored humidity for an opened spool is too high."""

    _attr_has_entity_name = True
    _attr_translation_key = "humidity_alert"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_icon = "mdi:water-percent"

    def __init__(self, entry: ConfigEntry, source_entity_id: str, *, device_info: DeviceInfo) -> None:
        self._entry = entry
        self._source_entity_id = source_entity_id
        self._threshold = entry.options.get(CONF_HUMIDITY_MAX, DEFAULT_HUMIDITY_MAX)
        self._current_humidity: float | None = None
        self._attr_unique_id = f"{entry.entry_id}_humidity_alert"
        self._attr_device_info = device_info
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
        was_on = self._attr_is_on
        new_state = event.data["new_state"]
        self._update_from_state(new_state.state if new_state else None)
        self.async_write_ha_state()
        async_handle_alert_transition(
            self.hass,
            self._entry,
            kind="humidity",
            was_on=was_on,
            is_on=self._attr_is_on,
            title=f"{self._entry.title}: Luftfeuchtigkeit zu hoch",
            message=(
                f"Aktuell {self._current_humidity:.0f}% (Grenzwert {self._threshold}%)."
                if self._current_humidity is not None
                else "Luftfeuchtigkeit über dem Grenzwert."
            ),
        )

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


class FilamentLowStockAlert(BinarySensorEntity):
    """Warns when a spool's remaining amount drops below a configured threshold."""

    _attr_has_entity_name = True
    _attr_translation_key = "low_stock_alert"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:package-variant-minus"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._threshold = entry.options[CONF_LOW_STOCK_THRESHOLD]
        self._percent: float | None = None
        self._attr_unique_id = f"{entry.entry_id}_low_stock_alert"
        self._attr_device_info = spool_device_info(entry)
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Start tracking the spool's live remaining weight."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_spool_updated(self._entry.entry_id), self._handle_update)
        )
        self._recompute()

    @callback
    def _handle_update(self) -> None:
        was_on = self._attr_is_on
        self._recompute()
        self.async_write_ha_state()
        async_handle_alert_transition(
            self.hass,
            self._entry,
            kind="low_stock",
            was_on=was_on,
            is_on=self._attr_is_on,
            title=f"{self._entry.title}: Bestand niedrig",
            message=f"Nur noch {self._percent}% übrig (Grenzwert {self._threshold}%).",
        )

    def _recompute(self) -> None:
        total = self._entry.options.get(CONF_TOTAL_WEIGHT)
        remaining = self._entry.runtime_data.remaining_weight
        self._percent = round(remaining / total * 100, 1) if total else None
        self._attr_is_on = self._percent is not None and self._percent < self._threshold

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        """Return diagnostic attributes for the low-stock alert."""
        return {"remaining_percentage": self._percent, "threshold": self._threshold}
