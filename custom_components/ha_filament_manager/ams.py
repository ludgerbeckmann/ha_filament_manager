"""Couple a spool to an AMS slot of the Bambu Lab printer integration.

The printer integration (github.com/greghesp/ha-bambulab) exposes every AMS
slot as a sensor whose attributes describe the tray: `empty`, `unknown`,
`tray_uuid` / `tag_uid` (the spool's RFID, all zeros for third-party spools),
`remain` (percent, -1 = unknown) and more. Nothing here talks to the printer
or to Bambu's cloud - everything comes from Home Assistant's state machine,
so a spool without an AMS slot (or without that integration) is unaffected.

A slot can hold any spool, so a spool only counts as "in the printer" while
the RFID in the slot is the one it was first seen with (it is learned the
first time the slot shows a valid RFID, and forgotten when the spool is
refilled or assigned to another slot).

The tray attributes and the rule for valid RFID values follow the AMS bridge
of Bambu Filaments (github.com/Timmes123/ha-bambu-filaments, MIT licence,
(c) 2026 Timmes123), which reads the same sensors.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    CONF_AMS_SLOT,
    CONF_AMS_SYNC,
    DOMAIN,
    SUBENTRY_TYPE_SPOOL,
    signal_ams_remaining,
    signal_ams_updated,
)

BAMBULAB_DOMAIN = "bambu_lab"

# unique_id of ha-bambulab's AMS tray sensors:
#   {device_type}_{printer_serial}_AMS_{ams_serial}_tray_{1..4}
_AMS_TRAY_RE = re.compile(r"^[^_]+_[^_]+_AMS_[^_]+_tray_\d+$")
_HEX32_RE = re.compile(r"^[0-9A-F]{32}$")


def slot_entities(hass: HomeAssistant) -> list[str]:
    """Return the entity ids of all AMS tray sensors of the Bambu Lab integration."""
    return sorted(
        entry.entity_id
        for entry in er.async_get(hass).entities.values()
        if entry.platform == BAMBULAB_DOMAIN
        and entry.domain == "sensor"
        and not entry.disabled
        and _AMS_TRAY_RE.match(entry.unique_id or "")
    )


def _valid_uid(value: Any) -> bool:
    """Bambu's own rule: non-empty and not all zeros."""
    return isinstance(value, str) and bool(value) and any(char != "0" for char in value)


@dataclass(frozen=True)
class SlotStatus:
    """What a slot sensor currently says."""

    available: bool
    loaded: bool
    rfid: str | None  # None: no spool, or a spool without RFID
    remain: int | None  # percent, None when unknown


def read_slot(hass: HomeAssistant, entity_id: str) -> SlotStatus:
    """Read a tray sensor into a SlotStatus."""
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return SlotStatus(False, False, None, None)
    attrs = state.attributes
    if attrs.get("empty") or attrs.get("unknown"):
        return SlotStatus(True, False, None, None)

    tray_uuid = str(attrs.get("tray_uuid") or "").upper()
    rfid = (
        tray_uuid
        if _HEX32_RE.match(tray_uuid) and _valid_uid(tray_uuid) and _valid_uid(attrs.get("tag_uid"))
        else None
    )
    try:
        remain: int | None = int(attrs.get("remain", -1))
    except (TypeError, ValueError):
        remain = None
    if remain is not None and remain < 0:
        remain = None
    return SlotStatus(True, True, rfid, None if remain is None else min(remain, 100))


@dataclass(frozen=True)
class SpoolAmsState:
    """Whether a spool is in the printer, and the remaining percentage it may follow."""

    available: bool = False
    in_printer: bool = False
    rfid_known: bool = False
    remain: int | None = None  # percent from the AMS, only when this spool's RFID is in the slot


def evaluate(learned: str | None, slot: SlotStatus) -> tuple[SpoolAmsState, str | None]:
    """Decide what the slot means for a spool; returns (state, learned RFID)."""
    if not slot.available:
        return SpoolAmsState(), learned
    if not slot.loaded:
        return SpoolAmsState(available=True, rfid_known=learned is not None), learned
    if slot.rfid is None:
        # A spool without RFID: assume it is ours unless we know ours carries one.
        return SpoolAmsState(available=True, in_printer=learned is None, rfid_known=False), learned
    if learned is None:
        learned = slot.rfid  # first sight: this is our spool
    mine = slot.rfid == learned
    return (
        SpoolAmsState(available=True, in_printer=mine, rfid_known=True, remain=slot.remain if mine else None),
        learned,
    )


class AmsTracker:
    """Follows the AMS slots assigned to the hub's spools."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._slots: dict[str, str] = {}
        self._sync: dict[str, bool] = {}
        for subentry_id, subentry in entry.subentries.items():
            if subentry.subentry_type == SUBENTRY_TYPE_SPOOL and subentry.data.get(CONF_AMS_SLOT):
                self._slots[subentry_id] = subentry.data[CONF_AMS_SLOT]
                self._sync[subentry_id] = bool(subentry.data.get(CONF_AMS_SYNC, True))
        self._learned: dict[str, str] = {}
        self._last_remain: dict[str, int | None] = {}
        self._store: Store[dict[str, dict[str, str]]] = Store(hass, 1, f"{DOMAIN}.ams_{entry.entry_id}")
        self.states: dict[str, SpoolAmsState] = {}
        self._unsubscribe: list[Any] = []

    async def async_start(self) -> None:
        """Load what was learned, then follow the slot sensors."""
        stored = await self._store.async_load() or {}
        for subentry_id, slot in self._slots.items():
            record = stored.get(subentry_id)
            # A different slot means a different spool - start over.
            if record and record.get("slot") == slot and record.get("rfid"):
                self._learned[subentry_id] = record["rfid"]

        if self._slots:
            self._unsubscribe.append(
                async_track_state_change_event(self._hass, sorted(set(self._slots.values())), self._handle_event)
            )
        for subentry_id in self._slots:
            self._update(subentry_id, initial=True)

    @callback
    def async_stop(self) -> None:
        """Stop following the slot sensors."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    def learned_rfid(self, subentry_id: str) -> str | None:
        """The RFID learned for a spool, if any."""
        return self._learned.get(subentry_id)

    @callback
    def forget(self, subentry_id: str) -> None:
        """Forget the learned RFID, e.g. after a new spool replaced the old one."""
        if subentry_id not in self._slots:
            return
        self._learned.pop(subentry_id, None)
        self._last_remain.pop(subentry_id, None)
        self._update(subentry_id, initial=True)

    @callback
    def _handle_event(self, event: Event) -> None:
        for subentry_id, slot in self._slots.items():
            if slot == event.data["entity_id"]:
                self._update(subentry_id)

    @callback
    def _update(self, subentry_id: str, *, initial: bool = False) -> None:
        learned = self._learned.get(subentry_id)
        state, new_learned = evaluate(learned, read_slot(self._hass, self._slots[subentry_id]))
        if new_learned != learned and new_learned is not None:
            self._learned[subentry_id] = new_learned
            self._hass.async_create_task(self._async_save())

        previous = self._last_remain.get(subentry_id)
        self._last_remain[subentry_id] = state.remain
        self.states[subentry_id] = state
        async_dispatcher_send(self._hass, signal_ams_updated(subentry_id))

        # Follow the AMS only when its percentage actually changes - not on
        # every state update and not at startup, so a value the user set by
        # hand stays until the AMS reports something new.
        if (
            not initial
            and self._sync.get(subentry_id)
            and state.remain is not None
            and previous is not None
            and state.remain != previous
        ):
            async_dispatcher_send(self._hass, signal_ams_remaining(subentry_id), state.remain)

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                subentry_id: {"slot": self._slots[subentry_id], "rfid": rfid}
                for subentry_id, rfid in self._learned.items()
                if subentry_id in self._slots
            }
        )


async def async_move_learned_rfid(
    hass: HomeAssistant, source: ConfigEntry, target: ConfigEntry, subentry_id: str
) -> None:
    """Hand the RFID learned for a spool over to the hub it moves to."""
    source_store: Store[dict[str, dict[str, str]]] = Store(hass, 1, f"{DOMAIN}.ams_{source.entry_id}")
    records = await source_store.async_load() or {}
    record = records.pop(subentry_id, None)
    if record is None:
        return
    await source_store.async_save(records)
    target_store: Store[dict[str, dict[str, str]]] = Store(hass, 1, f"{DOMAIN}.ams_{target.entry_id}")
    target_records = await target_store.async_load() or {}
    target_records[subentry_id] = record
    await target_store.async_save(target_records)
