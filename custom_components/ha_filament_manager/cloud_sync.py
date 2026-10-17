"""Matches a hub's spools with the Bambu cloud library and follows its remaining amount.

A spool is matched by the cloud spool picked in its settings or, when none is
picked, by the RFID the AMS coupling has learned for it. The remaining amount
is taken over when a spool is matched for the first time and afterwards
whenever the cloud's value changes - not at every start, so a value set by hand
stays until the cloud reports something new. Nothing is ever sent to the cloud.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.storage import Store

from .ams import AmsTracker
from .cloud import CloudSpool, cloud_spools
from .const import (
    CONF_CLOUD_SPOOL,
    CONF_CLOUD_SYNC,
    DOMAIN,
    SIGNAL_CLOUD_UPDATED,
    SUBENTRY_TYPE_SPOOL,
    signal_ams_updated,
    signal_cloud_matched,
    signal_cloud_remaining,
)


class CloudSync:
    """Follows the cloud library for the spools of one hub."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, ams: AmsTracker) -> None:
        self._hass = hass
        self._ams = ams
        self._manual: dict[str, int | None] = {}
        self._sync: dict[str, bool] = {}
        for subentry_id, subentry in entry.subentries.items():
            if subentry.subentry_type != SUBENTRY_TYPE_SPOOL:
                continue
            chosen = str(subentry.data.get(CONF_CLOUD_SPOOL) or "")
            self._manual[subentry_id] = int(chosen) if chosen.isdigit() else None
            self._sync[subentry_id] = bool(subentry.data.get(CONF_CLOUD_SYNC, True))
        self._store: Store[dict[str, dict[str, int]]] = Store(hass, 1, f"{DOMAIN}.cloud_{entry.entry_id}")
        self._seen: dict[str, dict[str, int]] = {}
        self.matches: dict[str, CloudSpool] = {}
        self._unsubscribe: list = []

    async def async_start(self) -> None:
        """Load what was seen last time and follow the cloud and the AMS."""
        self._seen = await self._store.async_load() or {}
        self._unsubscribe.append(
            async_dispatcher_connect(self._hass, SIGNAL_CLOUD_UPDATED, self._update_all)
        )
        for subentry_id in self._manual:
            # The AMS learns RFIDs after the fact; a spool may get matched then.
            self._unsubscribe.append(
                async_dispatcher_connect(
                    self._hass, signal_ams_updated(subentry_id), callback(lambda s=subentry_id: self._update(s))
                )
            )
        self._update_all()

    @callback
    def async_stop(self) -> None:
        """Stop following."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    @callback
    def _update_all(self) -> None:
        for subentry_id in self._manual:
            self._update(subentry_id)

    def _match(self, subentry_id: str, library: dict[int, CloudSpool]) -> CloudSpool | None:
        if (chosen := self._manual.get(subentry_id)) is not None:
            return library.get(chosen)
        if rfid := self._ams.learned_rfid(subentry_id):
            return next((spool for spool in library.values() if spool.rfid == rfid.upper()), None)
        return None

    @callback
    def _update(self, subentry_id: str) -> None:
        library = cloud_spools(self._hass)
        match = self._match(subentry_id, library) if library else None
        previous = self.matches.get(subentry_id)
        if match is None:
            if previous is not None and library is not None:
                del self.matches[subentry_id]
                async_dispatcher_send(self._hass, signal_cloud_matched(subentry_id))
            return  # no cloud (or it does not answer): everything stays as it is
        self.matches[subentry_id] = match
        if previous != match:
            async_dispatcher_send(self._hass, signal_cloud_matched(subentry_id))

        if not self._sync.get(subentry_id) or match.remaining is None:
            return
        seen = self._seen.get(subentry_id)
        if seen is not None and seen.get("cloud_id") == match.id and seen.get("remaining") == match.remaining:
            return
        self._seen[subentry_id] = {"cloud_id": match.id, "remaining": match.remaining}
        self._hass.async_create_task(self._store.async_save(self._seen))
        if (percent := match.percent) is not None:
            async_dispatcher_send(self._hass, signal_cloud_remaining(subentry_id), percent)
