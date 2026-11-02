"""The inventory: filament boxes and spools, kept in one storage file.

A *box* is a place spools are stored (a filament dry box, a shelf, ...). A
*spool* is either in a box or - unopened - in the stock ("Vorrat"), where it
belongs to no box. Everything is managed from the dashboard card (or the
services); Home Assistant entities only mirror what is in a box.

The manager is the single source of truth. It saves lazily, tells listeners
about every change and validates what is stored (a spool in a box must have
that box, the box's spool limit holds, ...). Errors are raised as
`FilamentError` carrying a translation key, which the services turn into
translated validation errors.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import ulid as ulid_util

from .const import (
    DEFAULT_HUMIDITY_DELAY,
    DEFAULT_HUMIDITY_MAX,
    DOMAIN,
    SIGNAL_SNAPSHOT_DIRTY,
    signal_box_updated,
    signal_spool_updated,
    suggested_humidity_delay,
    suggested_humidity_max,
)

STORAGE_VERSION = 1
SAVE_DELAY = 1.0


class FilamentError(Exception):
    """A rejected change; `key` is the translation key of the error message."""

    def __init__(self, key: str, **placeholders: str) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = placeholders


@dataclass
class Box:
    """A filament box (or shelf) with its humidity monitoring and notification settings."""

    id: str
    name: str
    humidity_sensor: str | None = None
    humidity_max: float | None = None  # None = automatic, from the materials inside
    humidity_delay: float | None = None  # minutes; None = automatic
    notify_targets: list[str] = field(default_factory=list)
    persistent_notification: bool = False
    spool_limit: int | None = None  # None = any number of spools

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Box:
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in known})


@dataclass
class Spool:
    """One filament spool, in a box or (sealed) in the stock."""

    id: str
    name: str
    material: str
    color: str
    manufacturer: str = ""
    diameter: str = "1.75"
    total_weight: float = 1000
    remaining_weight: float = 1000
    box_id: str | None = None  # None only for sealed spools (the stock)
    sealed: bool = False
    ams_slot: str | None = None  # a tray sensor of the Bambu Lab integration
    ams_sync: bool = True
    cloud_spool: str | None = None  # a spool of the Bambu cloud library (None = by RFID)
    cloud_sync: bool = True
    low_stock_threshold: float | None = None
    notify_targets: list[str] = field(default_factory=list)
    persistent_notification: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Spool:
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in known})


@dataclass
class PrintSettings:
    """The print notification: a Live Activity / progress notification for a Bambu Lab printer."""

    enabled: bool = False
    printer: str | None = None  # serial of the printer; None = the only one there is
    targets: list[str] = field(default_factory=list)  # notify services, e.g. "mobile_app_iphone"
    url: str = ""  # opened when the notification is tapped
    show_filament: bool = True  # name the spool in use

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PrintSettings:
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in known})


# What update_box / update_spool may change (everything but the id).
BOX_FIELDS = {f.name for f in fields(Box)} - {"id"}
SPOOL_FIELDS = {f.name for f in fields(Spool)} - {"id"}


class FilamentManager:
    """Holds boxes and spools, saves them and announces changes."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.data")
        self.boxes: dict[str, Box] = {}
        self.spools: dict[str, Spool] = {}
        self.print_settings = PrintSettings()
        self._listeners: list[Callable[[bool], None]] = []

    # ------------------------------------------------------------ persistence

    async def async_load(self) -> None:
        """Read the inventory."""
        raw = await self._store.async_load() or {}
        self.boxes = {box["id"]: Box.from_dict(box) for box in raw.get("boxes", [])}
        self.spools = {spool["id"]: Spool.from_dict(spool) for spool in raw.get("spools", [])}
        self.print_settings = PrintSettings.from_dict(raw.get("print_notification", {}))

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "boxes": [asdict(box) for box in self.boxes.values()],
            "spools": [asdict(spool) for spool in self.spools.values()],
            "print_notification": asdict(self.print_settings),
        }

    @callback
    def _save_soon(self) -> None:
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)

    async def async_flush(self) -> None:
        """Write the inventory now (before an unload; a delayed save would be lost)."""
        await self._store.async_save(self._data_to_save())

    async def async_save_now(self) -> None:
        """Write the inventory immediately (used by the migration)."""
        await self._store.async_save(self._data_to_save())

    # -------------------------------------------------------------- listeners

    @callback
    def async_add_listener(self, listener: Callable[[bool], None]) -> CALLBACK_TYPE:
        """Call `listener(structure_changed)` after every change.

        `structure_changed` is False for plain remaining-weight changes, which
        entities do not need to be re-created for.
        """
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def _changed(self, *, structure: bool, spool_id: str | None = None, box_id: str | None = None) -> None:
        self._save_soon()
        if spool_id is not None:
            async_dispatcher_send(self.hass, signal_spool_updated(spool_id))
        if box_id is not None:
            async_dispatcher_send(self.hass, signal_box_updated(box_id))
        for listener in list(self._listeners):
            listener(structure)
        async_dispatcher_send(self.hass, SIGNAL_SNAPSHOT_DIRTY)

    # ------------------------------------------------------------------ boxes

    def spools_in(self, box_id: str) -> list[Spool]:
        """The spools stored in a box (the stock has no box)."""
        return [spool for spool in self.spools.values() if spool.box_id == box_id]

    def stock(self) -> list[Spool]:
        """The sealed spools."""
        return [spool for spool in self.spools.values() if spool.sealed]

    def box_is_full(self, box_id: str, *, ignore: str | None = None) -> bool:
        """True when the box's spool limit is reached (ignoring one spool, e.g. the one being moved)."""
        box = self.boxes[box_id]
        if not box.spool_limit:
            return False
        count = sum(1 for spool in self.spools_in(box_id) if spool.id != ignore)
        return count >= box.spool_limit

    def _box(self, box_id: str) -> Box:
        if box_id not in self.boxes:
            raise FilamentError("box_not_found")
        return self.boxes[box_id]

    @callback
    def add_box(self, name: str, **settings: Any) -> Box:
        """Create a box."""
        name = (name or "").strip()
        if not name:
            raise FilamentError("name_required")
        box = Box(id=ulid_util.ulid_now(), name=name, **self._clean(settings, BOX_FIELDS))
        self.boxes[box.id] = box
        self._changed(structure=True, box_id=box.id)
        return box

    @callback
    def update_box(self, box_id: str, **changes: Any) -> Box:
        """Change a box's name or settings."""
        box = self._box(box_id)
        changes = self._clean(changes, BOX_FIELDS)
        if "name" in changes and not (changes["name"] or "").strip():
            raise FilamentError("name_required")
        limit = changes.get("spool_limit")
        if limit and len(self.spools_in(box_id)) > limit:
            raise FilamentError("limit_below_count", box=box.name)
        for key, value in changes.items():
            setattr(box, key, value.strip() if key == "name" else value)
        self._changed(structure=True, box_id=box_id)
        return box

    @callback
    def remove_box(self, box_id: str) -> None:
        """Delete an empty box."""
        box = self._box(box_id)
        if self.spools_in(box_id):
            raise FilamentError("box_not_empty", box=box.name)
        del self.boxes[box_id]
        self._changed(structure=True, box_id=box_id)

    # ----------------------------------------------------------------- spools

    def _spool(self, spool_id: str) -> Spool:
        if spool_id not in self.spools:
            raise FilamentError("spool_not_found")
        return self.spools[spool_id]

    @staticmethod
    def _clean(values: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
        """Keep only known fields; empty strings of optional fields mean "not set"."""
        cleaned = {key: value for key, value in values.items() if key in allowed}
        for key in ("humidity_sensor", "ams_slot", "cloud_spool"):
            if key in cleaned and not cleaned[key]:
                cleaned[key] = None
        # A limit of 0 means "none"; only a delay of 0 is meaningful (alert at once).
        for key in ("humidity_max", "spool_limit", "low_stock_threshold"):
            if key in cleaned and cleaned[key] in ("", 0):
                cleaned[key] = None
        if cleaned.get("humidity_delay") == "":
            cleaned["humidity_delay"] = None
        return cleaned

    def _check_room(self, box_id: str, *, ignore: str | None = None) -> None:
        box = self._box(box_id)
        if self.box_is_full(box_id, ignore=ignore):
            raise FilamentError("box_full", box=box.name)

    @callback
    def add_spool(
        self,
        *,
        name: str,
        material: str,
        color: str,
        box_id: str | None = None,
        sealed: bool = False,
        **details: Any,
    ) -> Spool:
        """Create a spool, in a box or - sealed, without a box - in the stock."""
        if sealed:
            box_id = None
        elif box_id is None:
            raise FilamentError("box_required")
        else:
            self._check_room(box_id)
        details = self._clean(details, SPOOL_FIELDS)
        total = details.setdefault("total_weight", 1000)
        details.setdefault("remaining_weight", total)
        if details["remaining_weight"] > total:
            raise FilamentError("remaining_exceeds_total")
        if sealed:
            details["ams_slot"] = None
        spool = Spool(
            id=ulid_util.ulid_now(),
            name=name.strip(),
            material=material.strip(),
            color=color.strip(),
            box_id=box_id,
            sealed=sealed,
            **details,
        )
        self.spools[spool.id] = spool
        self._changed(structure=True, spool_id=spool.id, box_id=box_id)
        return spool

    @callback
    def update_spool(self, spool_id: str, **changes: Any) -> Spool:
        """Change a spool's details (not where it is: see move/open)."""
        spool = self._spool(spool_id)
        changes = self._clean(changes, SPOOL_FIELDS - {"box_id", "sealed", "remaining_weight"})
        if "name" in changes and not (changes["name"] or "").strip():
            raise FilamentError("name_required")
        if spool.sealed:
            changes.pop("ams_slot", None)
        total = changes.get("total_weight", spool.total_weight)
        for key, value in changes.items():
            setattr(spool, key, value.strip() if key in ("name", "material", "color") else value)
        spool.remaining_weight = min(spool.remaining_weight, total)
        self._changed(structure=True, spool_id=spool_id, box_id=spool.box_id)
        return spool

    @callback
    def set_remaining(self, spool_id: str, grams: float) -> None:
        """Set a spool's remaining weight (clamped to 0 .. total)."""
        spool = self._spool(spool_id)
        spool.remaining_weight = max(0, min(grams, spool.total_weight))
        self._changed(structure=False, spool_id=spool_id)

    @callback
    def move_spool(self, spool_id: str, box_id: str) -> Spool:
        """Put a spool into another box (or, for a sealed one, open it into a box)."""
        spool = self._spool(spool_id)
        self._box(box_id)
        if spool.box_id == box_id:
            return spool
        self._check_room(box_id, ignore=spool_id)
        old_box = spool.box_id
        spool.box_id = box_id
        spool.sealed = False
        self._changed(structure=True, spool_id=spool_id, box_id=box_id)
        if old_box:
            async_dispatcher_send(self.hass, signal_box_updated(old_box))
        return spool

    @callback
    def assign_slot(self, spool_id: str, slot: str | None) -> None:
        """Load a spool into an AMS slot (taking out the one that was there) or take it out."""
        spool = self._spool(spool_id)
        if slot:
            if spool.sealed:
                raise FilamentError("spool_sealed", spool=spool.name)
            for other in self.spools.values():
                if other.id != spool_id and other.ams_slot == slot:
                    other.ams_slot = None
                    async_dispatcher_send(self.hass, signal_spool_updated(other.id))
        spool.ams_slot = slot or None
        self._changed(structure=True, spool_id=spool_id)

    @callback
    def remove_spool(self, spool_id: str) -> None:
        """Delete a spool."""
        spool = self._spool(spool_id)
        del self.spools[spool_id]
        self._changed(structure=True, spool_id=spool_id, box_id=spool.box_id)

    # ------------------------------------------------------ print notification

    @callback
    def set_print_settings(self, **changes: Any) -> PrintSettings:
        """Change the print notification's settings."""
        allowed = {f.name for f in fields(PrintSettings)}
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == "printer":
                value = value or None
            elif key == "url":
                value = (value or "").strip()
            setattr(self.print_settings, key, value)
        self._changed(structure=True)
        return self.print_settings

    # --------------------------------------------------------------- snapshots

    def box_limits(self, box_id: str) -> tuple[float, float]:
        """The box's (max humidity %, alert delay minutes): explicit values win, else the strictest material inside."""
        box = self.boxes[box_id]
        materials = [spool.material for spool in self.spools_in(box_id)]
        threshold = box.humidity_max
        if threshold is None:
            threshold = min((suggested_humidity_max(m) for m in materials), default=DEFAULT_HUMIDITY_MAX)
        delay = box.humidity_delay
        if delay is None:
            delay = min((suggested_humidity_delay(m) for m in materials), default=DEFAULT_HUMIDITY_DELAY)
        return threshold, delay
