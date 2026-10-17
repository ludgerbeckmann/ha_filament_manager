"""Moving a spool from one box (hub) to another.

Home Assistant cannot move a subentry between config entries, so the spool is
re-created in the target hub - under the *same subentry id*. Every unique id
and device identifier of the spool is derived from that id, so its devices
and entities (entity ids, names, history, areas, ...) are simply re-pointed
at the target hub instead of being deleted and created anew.

Order matters: the source hub is unloaded first (so no entity of the spool is
alive twice), the target hub's reload-on-change is held back while the
registries are re-pointed, then the spool leaves the source hub, the target
reloads (and finds everything in place) and the source is set up again.
"""
from __future__ import annotations

import inspect
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .ams import async_move_learned_rfid
from .const import DOMAIN, MOVING, SUBENTRY_TYPE_SPOOL
from .entity import hub_device_id


# Home Assistant 2026.9 lets a device belong to a single config entry and
# subentry and deprecates adding/removing config entries on a device.
_MOVES_DEVICES = "new_config_entry_id" in inspect.signature(dr.DeviceRegistry.async_update_device).parameters


async def async_move_spool(
    hass: HomeAssistant,
    source: ConfigEntry,
    subentry: ConfigSubentry,
    target: ConfigEntry,
    *,
    title: str,
    data: dict[str, Any],
) -> None:
    """Move ``subentry`` from ``source`` to ``target``, saving ``title``/``data`` with it."""
    subentry_id = subentry.subentry_id

    # No entity of the spool may be alive while the target creates it again.
    await hass.config_entries.async_unload(source.entry_id)
    moving = hass.data.setdefault(DOMAIN, {}).setdefault(MOVING, set())
    moving.add(target.entry_id)
    try:
        await async_move_learned_rfid(hass, source, target, subentry_id)

        hass.config_entries.async_add_subentry(
            target,
            ConfigSubentry(
                data=data,
                subentry_id=subentry_id,
                subentry_type=SUBENTRY_TYPE_SPOOL,
                title=title,
                unique_id=subentry.unique_id,
            ),
        )
        _repoint_registries(hass, source, target, subentry_id)
        hass.config_entries.async_remove_subentry(source, subentry_id)
    finally:
        moving.discard(target.entry_id)
        # The held-back reload of the target, then the source comes back without the spool.
        await hass.config_entries.async_reload(target.entry_id)
        await hass.config_entries.async_setup(source.entry_id)


def _repoint_registries(
    hass: HomeAssistant, source: ConfigEntry, target: ConfigEntry, subentry_id: str
) -> None:
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    device = _spool_device(dev_reg, source, subentry_id)
    via_device_id = hub_device_id(hass, target)
    if device is not None and _MOVES_DEVICES:
        # A device belongs to one config entry and subentry: move it as a whole.
        dev_reg.async_update_device(
            device.id,
            new_config_entry_id=target.entry_id,
            new_config_subentry_id=subentry_id,
            via_device_id=via_device_id,
        )
    elif device is not None:
        # Older Home Assistant: link to the target first; removing the source
        # before would detach the entities from their device.
        dev_reg.async_update_device(
            device.id, add_config_entry_id=target.entry_id, add_config_subentry_id=subentry_id
        )
    for entity in list(er.async_entries_for_config_entry(ent_reg, source.entry_id)):
        if entity.config_subentry_id == subentry_id:
            ent_reg.async_update_entity(
                entity.entity_id, config_entry_id=target.entry_id, config_subentry_id=subentry_id
            )
    if device is not None and not _MOVES_DEVICES:
        dev_reg.async_update_device(
            device.id,
            remove_config_entry_id=source.entry_id,
            remove_config_subentry_id=subentry_id,
            via_device_id=via_device_id,
        )


def _spool_device(dev_reg: dr.DeviceRegistry, source: ConfigEntry, subentry_id: str) -> dr.DeviceEntry | None:
    identifier = (DOMAIN, subentry_id)
    if hasattr(dev_reg, "async_get_device_by_identifier"):
        return dev_reg.async_get_device_by_identifier(identifier, source.entry_id)
    return dev_reg.async_get_device(identifiers={identifier})  # Home Assistant before 2026.8
