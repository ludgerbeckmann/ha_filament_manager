"""Binary sensor platform for Filament Manager: humidity and low-stock alerts.

Both are optional and only created when configured for a spool. Each pushes
a notification (and/or creates a persistent notification) on the off -> on
transition, and clears it again on the on -> off transition - see
notify_helper.py.
"""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import (
    CONF_BOX,
    CONF_HUMIDITY_DELAY,
    CONF_HUMIDITY_MAX,
    CONF_HUMIDITY_SENSOR,
    CONF_LOW_STOCK_THRESHOLD,
    CONF_TOTAL_WEIGHT,
    DEFAULT_HUMIDITY_MAX,
    DOMAIN,
    SUBENTRY_TYPE_BOX,
    SUBENTRY_TYPE_SPOOL,
    signal_spool_updated,
)
from .boxes import effective_box_humidity_limits
from .entity import box_device_info, spool_device_info
from .notify_helper import async_handle_alert_transition


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the humidity and/or low-stock alert binary sensors, if configured."""
    for subentry_id, subentry in entry.subentries.items():
        entities: list[BinarySensorEntity] = []

        if subentry.subentry_type == SUBENTRY_TYPE_BOX:
            humidity_sensor = subentry.data.get(CONF_HUMIDITY_SENSOR)
            if humidity_sensor:
                threshold, delay = effective_box_humidity_limits(entry, subentry)
                entities.append(
                    FilamentHumidityAlert(
                        subentry,
                        humidity_sensor,
                        device_info=box_device_info(subentry),
                        threshold=threshold,
                        delay_minutes=delay,
                    )
                )
        elif subentry.subentry_type == SUBENTRY_TYPE_SPOOL:
            humidity_sensor = subentry.data.get(CONF_HUMIDITY_SENSOR)
            # A spool assigned to a box is monitored by the box's own humidity
            # sensor instead - its own (if still configured) is ignored, and
            # any entity left over from before it was assigned is removed (it
            # would otherwise linger as a stale, "unavailable" registry entry
            # that still shows up on the overview card).
            has_box = bool(subentry.data.get(CONF_BOX))
            if humidity_sensor and not has_box:
                entities.append(
                    FilamentHumidityAlert(
                        subentry,
                        humidity_sensor,
                        device_info=spool_device_info(subentry),
                        threshold=subentry.data.get(CONF_HUMIDITY_MAX, DEFAULT_HUMIDITY_MAX),
                        # Entries created before the delay existed have no value -> no delay.
                        delay_minutes=subentry.data.get(CONF_HUMIDITY_DELAY) or 0,
                    )
                )
            elif has_box:
                _async_remove_humidity_alert_entity(hass, subentry)

            if subentry.data.get(CONF_LOW_STOCK_THRESHOLD) is not None:
                entities.append(FilamentLowStockAlert(entry, subentry))

        if entities:
            async_add_entities(entities, config_subentry_id=subentry_id)


def _async_remove_humidity_alert_entity(hass: HomeAssistant, subentry: ConfigSubentry) -> None:
    """Remove a spool's own humidity alert entity, now superseded by its box."""
    registry = er.async_get(hass)
    unique_id = f"{subentry.subentry_id}_humidity_alert"
    if (entity_id := registry.async_get_entity_id("binary_sensor", DOMAIN, unique_id)) is not None:
        registry.async_remove(entity_id)


class FilamentHumidityAlert(BinarySensorEntity):
    """Warns when the monitored humidity for an opened spool/box is too high.

    With a configured delay (minutes), the alert only turns on once the
    humidity has stayed above the threshold for that long without dropping
    back below it - short spikes (opening the box) are ignored.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "humidity_alert"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_icon = "mdi:water-percent"

    def __init__(
        self,
        subentry: ConfigSubentry,
        source_entity_id: str,
        *,
        device_info: DeviceInfo,
        threshold: float,
        delay_minutes: float,
    ) -> None:
        self._subentry = subentry
        self._source_entity_id = source_entity_id
        self._threshold = threshold
        self._delay_minutes = float(delay_minutes)
        self._current_humidity: float | None = None
        self._over_threshold = False
        self._cancel_delay: CALLBACK_TYPE | None = None
        self._attr_unique_id = f"{subentry.subentry_id}_humidity_alert"
        self._attr_device_info = device_info
        self._attr_available = False
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Start tracking the referenced humidity sensor."""
        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._source_entity_id], self._handle_source_event)
        )
        self.async_on_remove(self._cancel_pending_delay)
        if (state := self.hass.states.get(self._source_entity_id)) is not None:
            self._update_from_state(state.state)

    @callback
    def _cancel_pending_delay(self) -> None:
        if self._cancel_delay is not None:
            self._cancel_delay()
            self._cancel_delay = None

    @callback
    def _handle_source_event(self, event: Event) -> None:
        was_on = self._attr_is_on
        new_state = event.data["new_state"]
        self._update_from_state(new_state.state if new_state else None)
        self.async_write_ha_state()
        self._notify_transition(was_on)

    @callback
    def _delay_elapsed(self, _now: datetime) -> None:
        """Humidity stayed above the threshold for the whole grace period."""
        self._cancel_delay = None
        if not self._over_threshold or self._attr_is_on:
            return
        self._attr_is_on = True
        self.async_write_ha_state()
        self._notify_transition(False)

    def _notify_transition(self, was_on: bool) -> None:
        async_handle_alert_transition(
            self.hass,
            self._subentry,
            kind="humidity",
            was_on=was_on,
            is_on=self._attr_is_on,
            title=f"{self._subentry.title}: Luftfeuchtigkeit zu hoch",
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
            self._over_threshold = False
            self._cancel_pending_delay()
            self._attr_available = False
            self._attr_is_on = False
            return

        self._attr_available = True
        self._over_threshold = self._current_humidity > self._threshold

        if not self._over_threshold:
            self._cancel_pending_delay()
            self._attr_is_on = False
        elif self._delay_minutes <= 0:
            self._attr_is_on = True
        elif not self._attr_is_on and self._cancel_delay is None:
            # Start the grace period; already-on stays on while still too humid.
            self._cancel_delay = async_call_later(
                self.hass, self._delay_minutes * 60, self._delay_elapsed
            )

    @property
    def extra_state_attributes(self) -> dict[str, float | str | bool | None]:
        """Return diagnostic attributes for the humidity alert."""
        return {
            "current_humidity": self._current_humidity,
            "threshold": self._threshold,
            "delay_minutes": self._delay_minutes,
            "over_threshold": self._over_threshold,
            "source_entity_id": self._source_entity_id,
        }


class FilamentLowStockAlert(BinarySensorEntity):
    """Warns when a spool's remaining amount drops below a configured threshold."""

    _attr_has_entity_name = True
    _attr_translation_key = "low_stock_alert"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:package-variant-minus"

    def __init__(self, entry: ConfigEntry, subentry: ConfigSubentry) -> None:
        self._entry = entry
        self._subentry = subentry
        self._threshold = subentry.data[CONF_LOW_STOCK_THRESHOLD]
        self._percent: float | None = None
        self._attr_unique_id = f"{subentry.subentry_id}_low_stock_alert"
        self._attr_device_info = spool_device_info(subentry)
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Start tracking the spool's live remaining weight."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_spool_updated(self._subentry.subentry_id), self._handle_update
            )
        )
        self._recompute()

    @callback
    def _handle_update(self) -> None:
        was_on = self._attr_is_on
        self._recompute()
        self.async_write_ha_state()
        async_handle_alert_transition(
            self.hass,
            self._subentry,
            kind="low_stock",
            was_on=was_on,
            is_on=self._attr_is_on,
            title=f"{self._subentry.title}: Bestand niedrig",
            message=f"Nur noch {self._percent}% übrig (Grenzwert {self._threshold}%).",
        )

    def _recompute(self) -> None:
        total = self._subentry.data.get(CONF_TOTAL_WEIGHT)
        remaining = self._entry.runtime_data[self._subentry.subentry_id].remaining_weight
        self._percent = round(remaining / total * 100, 1) if total else None
        self._attr_is_on = self._percent is not None and self._percent < self._threshold

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        """Return diagnostic attributes for the low-stock alert."""
        return {"remaining_percentage": self._percent, "threshold": self._threshold}
