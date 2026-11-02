"""Matches a hub's spools with the Bambu cloud library and follows its remaining amount.

A spool is matched by the cloud spool picked in its settings or, when none is
picked, by the RFID the AMS coupling has learned for it. The remaining amount
is taken over when a spool is matched for the first time and afterwards
whenever the cloud's value changes - not at every start, so a value set by hand
stays until the cloud reports something new. Nothing is ever sent to the cloud.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.storage import Store

from .ams import AmsTracker
from .cloud import CloudSpool, cloud_spools
from .const import (
    DOMAIN,
    SIGNAL_AMS_ANY,
    SIGNAL_CLOUD_UPDATED,
    SIGNAL_SNAPSHOT_DIRTY,
    signal_cloud_matched,
    signal_cloud_remaining,
)
from .store import FilamentManager


class CloudSync:
    """Follows the cloud library for the spools."""

    def __init__(self, hass: HomeAssistant, manager: FilamentManager, ams: AmsTracker) -> None:
        self._hass = hass
        self._manager = manager
        self._ams = ams
        self._store: Store[dict[str, dict[str, int]]] = Store(hass, 1, f"{DOMAIN}.cloud")
        self._seen: dict[str, dict[str, int]] = {}
        self.matches: dict[str, CloudSpool] = {}
        self._unsubscribe: list = []

    async def async_start(self) -> None:
        """Load what was seen last time and follow the cloud and the AMS."""
        self._seen = await self._store.async_load() or {}
        self._unsubscribe.append(async_dispatcher_connect(self._hass, SIGNAL_CLOUD_UPDATED, self._update_all))
        # The AMS learns RFIDs after the fact (a spool may get matched then).
        self._unsubscribe.append(async_dispatcher_connect(self._hass, SIGNAL_AMS_ANY, self._update_all))
        self._update_all()

    @callback
    def async_stop(self) -> None:
        """Stop following."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    @callback
    def reconfigure(self) -> None:
        """Pick up changed cloud choices; forget matches of spools that are gone."""
        for spool_id in set(self.matches) - set(self._manager.spools):
            del self.matches[spool_id]
        self._update_all()

    @callback
    def _update_all(self) -> None:
        for spool in list(self._manager.spools.values()):
            if not spool.sealed:
                self._update(spool.id)

    def _match(self, spool_id: str, library: dict[int, CloudSpool]) -> CloudSpool | None:
        spool = self._manager.spools[spool_id]
        if (chosen := str(spool.cloud_spool or "")).isdigit():
            return library.get(int(chosen))
        if rfid := self._ams.learned_rfid(spool_id):
            return next((spool for spool in library.values() if spool.rfid == rfid.upper()), None)
        return None

    @callback
    def _update(self, spool_id: str) -> None:
        spool = self._manager.spools[spool_id]
        library = cloud_spools(self._hass)
        match = self._match(spool_id, library) if library else None
        previous = self.matches.get(spool_id)
        if match is None:
            if previous is not None and library is not None:
                del self.matches[spool_id]
                async_dispatcher_send(self._hass, signal_cloud_matched(spool_id))
                async_dispatcher_send(self._hass, SIGNAL_SNAPSHOT_DIRTY)
            return  # no cloud (or it does not answer): everything stays as it is
        self.matches[spool_id] = match
        if previous != match:
            async_dispatcher_send(self._hass, signal_cloud_matched(spool_id))
            async_dispatcher_send(self._hass, SIGNAL_SNAPSHOT_DIRTY)

        if not spool.cloud_sync or match.remaining is None:
            return
        seen = self._seen.get(spool_id)
        if seen is not None and seen.get("cloud_id") == match.id and seen.get("remaining") == match.remaining:
            return
        self._seen[spool_id] = {"cloud_id": match.id, "remaining": match.remaining}
        self._hass.async_create_task(self._store.async_save(self._seen))
        if (percent := match.percent) is not None:
            async_dispatcher_send(self._hass, signal_cloud_remaining(spool_id), percent)
