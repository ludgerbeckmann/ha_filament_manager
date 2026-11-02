"""A print notification for Bambu Lab printers, shown as Live Activity on iPhone/iPad.

Built on the sensors of the Bambu Lab integration (ha-bambulab: print status,
progress, remaining time, task name). While a print is prepared, running or
paused, one notification per target is kept up to date (iOS Live Activity /
Android live update: a progress bar, the remaining time, the job). When the
print ends it is replaced by a short "finished" or "failed" notification; when
the printer goes idle or offline it is cleared.

The targets are the `notify.mobile_app_*` services of the Companion apps: only
those take the extra data of a Live Activity (`live_update`, `progress`, ...).
Nothing is sent unless it is switched on and has targets.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .ams import BAMBULAB_DOMAIN
from .const import DOMAIN
from .store import FilamentManager

_LOGGER = logging.getLogger(__name__)

# Printer sensors of ha-bambulab: unique_id "{serial}_{key}".
_STATUS_RE = re.compile(r"^(?P<serial>[^_]+)_print_status$")
ACTIVE = ("prepare", "running", "pause")
ENDED = ("finish", "failed")
# Debounce: status and progress usually change together.
SETTLE_SECONDS = 0.5
TEST_CLEAR_SECONDS = 30
GREEN = "#00AE42"
ORANGE = "#FF9800"


@dataclass(frozen=True)
class Printer:
    """A Bambu Lab printer, as far as its sensors are known."""

    serial: str
    name: str


def printers(hass: HomeAssistant) -> list[Printer]:
    """The printers of the Bambu Lab integration (found by their print-status sensor)."""
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    found: list[Printer] = []
    for entry in ent_reg.entities.values():
        if entry.platform != BAMBULAB_DOMAIN or entry.domain != "sensor" or entry.disabled:
            continue
        if not (match := _STATUS_RE.match(entry.unique_id or "")):
            continue
        device = dev_reg.async_get(entry.device_id) if entry.device_id else None
        name = (device and (device.name_by_user or device.name)) or match.group("serial")
        found.append(Printer(match.group("serial"), name))
    return sorted(found, key=lambda printer: printer.name.casefold())


def notify_services(hass: HomeAssistant) -> list[str]:
    """The Companion apps' notify services (the only ones that can show a Live Activity)."""
    return sorted(name for name in hass.services.async_services_for_domain("notify") if name.startswith("mobile_app_"))


def format_remaining(minutes: float) -> str:
    """"1 h 5 min" / "5 min" ("" when nothing is left)."""
    total = int(minutes)
    if total <= 0:
        return ""
    hours, rest = divmod(total, 60)
    return f"{hours} h {rest} min" if hours else f"{rest} min"


class PrintNotifier:
    """Keeps the notifications of the selected printer up to date."""

    def __init__(self, hass: HomeAssistant, manager: FilamentManager) -> None:
        self._hass = hass
        self._manager = manager
        self._unsubscribe: CALLBACK_TYPE | None = None
        self._timer: CALLBACK_TYPE | None = None
        self._test_timer: CALLBACK_TYPE | None = None
        self._tracked: tuple[str, ...] = ()
        self._previous_status: str | None = None
        self._last_sent: tuple[Any, ...] | None = None
        self._live = False

    # -------------------------------------------------------------- lifecycle

    @callback
    def reconfigure(self) -> None:
        """Pick up changed settings (or new printers)."""
        printer = self._printer()
        settings = self._manager.print_settings
        tracked: tuple[str, ...] = ()
        if settings.enabled and settings.targets and printer is not None:
            tracked = tuple(
                entity for key in ("print_status", "print_progress", "subtask_name") if (entity := self._entity(printer, key))
            )
        if tracked == self._tracked:
            return
        self._stop_tracking()
        self._tracked = tracked
        self._live = False
        self._last_sent = None
        if tracked:
            self._previous_status = self._status(printer)  # a print that already ended is not announced again
            self._unsubscribe = async_track_state_change_event(self._hass, list(tracked), self._handle_event)
            self._schedule()

    @callback
    def async_stop(self) -> None:
        """Stop following the printer."""
        self._stop_tracking()
        self._tracked = ()
        if self._test_timer is not None:
            self._test_timer()
            self._test_timer = None

    def _stop_tracking(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._timer is not None:
            self._timer()
            self._timer = None

    # ---------------------------------------------------------------- sensors

    def _printer(self) -> Printer | None:
        found = printers(self._hass)
        wanted = self._manager.print_settings.printer
        if wanted:
            return next((printer for printer in found if printer.serial == wanted), None)
        return found[0] if len(found) == 1 else None

    def _entity(self, printer: Printer, key: str) -> str | None:
        return er.async_get(self._hass).async_get_entity_id("sensor", BAMBULAB_DOMAIN, f"{printer.serial}_{key}")

    def _state(self, printer: Printer, key: str):
        entity_id = self._entity(printer, key)
        state = self._hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            return None
        return state

    def _status(self, printer: Printer) -> str | None:
        state = self._state(printer, "print_status")
        return state.state.lower() if state else None

    def _remaining_minutes(self, printer: Printer) -> float:
        state = self._state(printer, "remaining_time")
        if state is None:
            return 0
        try:
            value = float(state.state)
        except ValueError:
            return 0
        unit = state.attributes.get("unit_of_measurement")
        return value * 60 if unit == "h" else value / 60 if unit == "s" else value

    def _job(self, printer: Printer) -> str:
        for key in ("subtask_name", "gcode_file"):
            if state := self._state(printer, key):
                return state.state
        return ""

    def _filament(self) -> str:
        """The spool in the tray the printer is using right now, if it is one of ours."""
        for spool in self._manager.spools.values():
            state = self._hass.states.get(spool.ams_slot) if spool.ams_slot else None
            if state is not None and state.attributes.get("active"):
                percent = round(spool.remaining_weight / spool.total_weight * 100) if spool.total_weight else None
                return f"{spool.name} ({percent} %)" if percent is not None else spool.name
        return ""

    # ----------------------------------------------------------------- events

    @callback
    def _handle_event(self, event: Event) -> None:
        self._schedule()

    @callback
    def _schedule(self) -> None:
        if self._timer is None:
            self._timer = async_call_later(self._hass, SETTLE_SECONDS, self._settled)

    async def _settled(self, _now: Any) -> None:
        self._timer = None
        if (printer := self._printer()) is None:
            return
        settings = self._manager.print_settings
        status = self._status(printer)
        previous, self._previous_status = self._previous_status, status

        if status in ACTIVE:
            payload = self._live_payload(printer, status)
            key = (payload["message"], payload["data"]["progress"], status)
            if key != self._last_sent:
                self._last_sent = key
                self._live = True
                await self._send(settings.targets, payload)
        elif status in ENDED:
            if previous != status:  # the print has just ended
                await self._send(settings.targets, self._clear_payload(printer))
                ok = status == "finish"
                final: dict[str, Any] = {
                    "title": f"{'✅' if ok else '❌'} {printer.name} – Druck {'fertig' if ok else 'fehlgeschlagen'}",
                    "message": self._job(printer) or " ",
                }
                if settings.url:
                    final["data"] = {"url": settings.url}
                await self._send(settings.targets, final)
            self._live = False
            self._last_sent = None
        elif self._live:  # idle, offline, ...: take the Live Activity away
            await self._send(settings.targets, self._clear_payload(printer))
            self._live = False
            self._last_sent = None

    # --------------------------------------------------------------- payloads

    def _tag(self, printer: Printer) -> str:
        return f"{DOMAIN}_print_{printer.serial}"

    def _live_payload(self, printer: Printer, status: str, **override: Any) -> dict[str, Any]:
        settings = self._manager.print_settings
        state = self._state(printer, "print_progress")
        try:
            progress = int(float(state.state)) if state else 0
        except ValueError:
            progress = 0
        job = override.get("job", self._job(printer))
        remaining = format_remaining(override.get("minutes", self._remaining_minutes(printer)))
        if status == "pause":
            head = "⏸ Pausiert"
        elif status == "prepare":
            head = "Vorbereitung"
        else:
            head = f"noch {remaining}" if remaining else ""
        filament = override.get("filament", self._filament() if settings.show_filament else "")
        message = " · ".join(part for part in (head, job, filament) if part) or printer.name
        data: dict[str, Any] = {
            "tag": self._tag(printer),
            "live_update": True,
            "progress": progress,
            "progress_max": 100,
            "critical_text": f"{progress} %",
            "notification_icon": "mdi:printer-3d",
            "notification_icon_color": ORANGE if status == "pause" else GREEN,
            "silent": True,
        }
        if settings.url:
            data["url"] = settings.url
        return {"title": printer.name, "message": message, "data": data}

    def _clear_payload(self, printer: Printer) -> dict[str, Any]:
        return {"message": "clear_notification", "data": {"tag": self._tag(printer)}}

    async def _send(self, targets: list[str], payload: dict[str, Any]) -> None:
        available = self._hass.services.async_services_for_domain("notify")
        for target in targets:
            if target not in available:
                _LOGGER.debug("Notify service notify.%s does not exist (any more)", target)
                continue
            try:
                await self._hass.services.async_call("notify", target, payload, blocking=True)
            except Exception:  # noqa: BLE001 - a device that is off must not stop the others
                _LOGGER.warning("Could not send the print notification to notify.%s", target, exc_info=True)

    # ------------------------------------------------------------------- test

    async def async_send_test(self) -> None:
        """Show a sample Live Activity (and take it away again after a short while)."""
        settings = self._manager.print_settings
        printer = self._printer() or Printer("test", "Bambu Lab")
        payload = self._live_payload(
            printer, "running", job="Testdruck", minutes=65, filament="PETG Rot (82 %)" if settings.show_filament else ""
        )
        payload["data"]["progress"] = 42
        payload["data"]["critical_text"] = "42 %"
        await self._send(settings.targets, payload)

        if self._test_timer is not None:
            self._test_timer()

        async def _clear(_now: Any) -> None:
            self._test_timer = None
            await self._send(settings.targets, self._clear_payload(printer))

        self._test_timer = async_call_later(self._hass, TEST_CLEAR_SECONDS, _clear)
