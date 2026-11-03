"""Binary sensor platform for Filament Manager: humidity, low-stock and in-printer.

All are optional and created only where they apply: the humidity alert belongs
to a box and exists when the box has a humidity sensor; the low-stock alert to
a spool with a threshold; "in printer" to a spool assigned to an AMS slot.
Alerts push a notification (and/or create a persistent notification) on the
off -> on transition and clear it again on on -> off - see notify_helper.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import signal_ams_updated, signal_box_updated, signal_spool_updated
from .entity import EntitySync, device_info
from .notify_helper import async_handle_alert_transition
from .runtime import FilamentRuntime


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the alerts and in-printer sensors where they are configured."""
    runtime: FilamentRuntime = entry.runtime_data

    def wanted() -> dict[str, Any]:
        found: dict[str, Any] = {}
        for box in runtime.manager.boxes.values():
            if box.humidity_sensor:
                found[f"{box.id}_humidity_alert"] = lambda box_id=box.id: FilamentHumidityAlert(runtime, box_id)
        for spool in runtime.manager.spools.values():
            if spool.sealed:
                continue
            if spool.low_stock_threshold is not None:
                found[f"{spool.id}_low_stock_alert"] = lambda spool_id=spool.id: FilamentLowStockAlert(
                    runtime, spool_id
                )
            if spool.ams_slot:
                found[f"{spool.id}_in_printer"] = lambda spool_id=spool.id: FilamentInPrinterSensor(
                    runtime, spool_id
                )
        return found

    sync = EntitySync(hass, "binary_sensor", async_add_entities, wanted)
    runtime.syncers.append(sync)
    sync()


class FilamentHumidityAlert(BinarySensorEntity):
    """Warns when the monitored humidity of a box is too high.

    With a delay (minutes), the alert only turns on once the humidity has
    stayed above the limit for that long without dropping back below it -
    short spikes (opening the box) are ignored. Sensor, limit and delay follow
    the box's settings and the materials inside, live.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "humidity_alert"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_icon = "mdi:water-percent"

    def __init__(self, runtime: FilamentRuntime, box_id: str) -> None:
        self._manager = runtime.manager
        self._box_id = box_id
        self._source: str | None = None
        self._threshold: float = 0
        self._delay_minutes: float = 0
        self._current_humidity: float | None = None
        self._over_threshold = False
        self._cancel_delay: CALLBACK_TYPE | None = None
        self._unsub_source: CALLBACK_TYPE | None = None
        self._attr_unique_id = f"{box_id}_humidity_alert"
        self._attr_device_info = device_info(box_id)
        self._attr_available = False
        self._attr_is_on = False

    @property
    def _box(self):
        return self._manager.boxes[self._box_id]

    async def async_added_to_hass(self) -> None:
        """Start tracking the humidity sensor and follow changes of the box's settings."""
        self.async_on_remove(self._stop)
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_box_updated(self._box_id), self._reconfigure)
        )
        self._reconfigure()

    @callback
    def _stop(self) -> None:
        self._cancel_pending_delay()
        if self._unsub_source is not None:
            self._unsub_source()
            self._unsub_source = None

    @callback
    def _reconfigure(self) -> None:
        """Pick up a new sensor, limit or delay."""
        if self._box_id not in self._manager.boxes or not self._box.humidity_sensor:
            return  # the entity is about to be removed
        threshold, delay = self._manager.box_limits(self._box_id)
        source = self._box.humidity_sensor
        changed = (source, threshold, float(delay)) != (self._source, self._threshold, self._delay_minutes)
        self._threshold, self._delay_minutes = threshold, float(delay)
        if source != self._source:
            if self._unsub_source is not None:
                self._unsub_source()
            self._source = source
            self._unsub_source = async_track_state_change_event(self.hass, [source], self._handle_source_event)
        if changed:
            self._cancel_pending_delay()
            state = self.hass.states.get(source)
            was_on = self._attr_is_on
            self._update_from_state(state.state if state is not None else None)
            self.async_write_ha_state()
            self._notify_transition(was_on)

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
        if self._box_id not in self._manager.boxes:
            return
        async_handle_alert_transition(
            self.hass,
            self._manager,
            self._box_id,
            kind="humidity",
            was_on=was_on,
            is_on=self._attr_is_on,
            title=f"{self._box.name}: Luftfeuchtigkeit zu hoch",
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
            self._cancel_delay = async_call_later(self.hass, self._delay_minutes * 60, self._delay_elapsed)

    @property
    def extra_state_attributes(self) -> dict[str, float | str | bool | None]:
        """Return diagnostic attributes for the humidity alert."""
        return {
            "current_humidity": self._current_humidity,
            "threshold": self._threshold,
            "delay_minutes": self._delay_minutes,
            "over_threshold": self._over_threshold,
            "source_entity_id": self._source,
            "box_id": self._box_id,
        }


class FilamentLowStockAlert(BinarySensorEntity):
    """Warns when a spool's remaining amount drops below a configured threshold."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "low_stock_alert"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:package-variant-minus"

    def __init__(self, runtime: FilamentRuntime, spool_id: str) -> None:
        self._manager = runtime.manager
        self._spool_id = spool_id
        self._percent: float | None = None
        self._threshold: float | None = None
        self._attr_unique_id = f"{spool_id}_low_stock_alert"
        self._attr_device_info = device_info(spool_id)
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Start tracking the spool's live remaining weight."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_spool_updated(self._spool_id), self._handle_update)
        )
        self._recompute()

    @callback
    def _handle_update(self) -> None:
        spool = self._manager.spools.get(self._spool_id)
        if spool is None or spool.low_stock_threshold is None:
            return  # about to be removed
        was_on = self._attr_is_on
        self._recompute()
        self.async_write_ha_state()
        async_handle_alert_transition(
            self.hass,
            self._manager,
            spool.id,
            kind="low_stock",
            was_on=was_on,
            is_on=self._attr_is_on,
            title=f"{spool.name}: Bestand niedrig",
            message=f"Nur noch {self._percent}% übrig (Grenzwert {self._threshold}%).",
        )

    def _recompute(self) -> None:
        spool = self._manager.spools.get(self._spool_id)
        if spool is None or spool.low_stock_threshold is None:
            return
        self._threshold = spool.low_stock_threshold
        self._percent = (
            round(spool.remaining_weight / spool.total_weight * 100, 1) if spool.total_weight else None
        )
        self._attr_is_on = self._percent is not None and self._percent < self._threshold

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        """Return diagnostic attributes for the low-stock alert."""
        return {"remaining_percentage": self._percent, "threshold": self._threshold}


class FilamentInPrinterSensor(BinarySensorEntity):
    """Whether this spool is currently in its AMS slot (a Bambu Lab printer)."""

    _attr_has_entity_name = True
    _attr_translation_key = "in_printer"
    _attr_icon = "mdi:printer-3d"
    _attr_should_poll = False

    def __init__(self, runtime: FilamentRuntime, spool_id: str) -> None:
        self._runtime = runtime
        self._spool_id = spool_id
        self._attr_unique_id = f"{spool_id}_in_printer"
        self._attr_device_info = device_info(spool_id)

    async def async_added_to_hass(self) -> None:
        """Follow the AMS slot's state."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_ams_updated(self._spool_id), self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def _state(self):
        return self._runtime.ams.states.get(self._spool_id)

    @property
    def available(self) -> bool:
        """Unavailable while the slot sensor (the printer) is."""
        return bool(self._state and self._state.available)

    @property
    def is_on(self) -> bool:
        """Return True while this spool sits in its slot."""
        return bool(self._state and self._state.in_printer)

    @property
    def extra_state_attributes(self) -> dict[str, str | int | bool | None]:
        """Return the slot and what the AMS reports."""
        spool = self._runtime.manager.spools.get(self._spool_id)
        state = self._state
        return {
            "ams_slot": spool.ams_slot if spool else None,
            "ams_remaining_percent": state.remain if state else None,
            "rfid_known": state.rfid_known if state else False,
        }
