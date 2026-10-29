"""Services and a websocket command for managing spools from the dashboard card.

Everything here works on the same data the config flow edits: spools are
subentries of a hub (box). A service takes the registry id of a spool's (or a
box's) device, which is what the card knows.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .ams import slot_entities
from .boxes import spool_subentries
from .cloud import hub_entries
from .config_flow import _suggest_name
from .const import (
    COLOR_OPTIONS,
    CONF_AMS_SLOT,
    CONF_COLOR,
    CONF_DIAMETER,
    CONF_INITIAL_REMAINING_WEIGHT,
    CONF_MANUFACTURER,
    CONF_MATERIAL,
    CONF_TOTAL_WEIGHT,
    DEFAULT_DIAMETER,
    DIAMETER_OPTIONS,
    DOMAIN,
    MANUFACTURER_OPTIONS,
    MATERIAL_OPTIONS,
    SERVICE_ADD_SPOOL,
    SERVICE_LOAD_SPOOL,
    SERVICE_MOVE_SPOOL,
    SERVICE_REMOVE_SPOOL,
    SERVICE_UNLOAD_SPOOL,
    SUBENTRY_TYPE_SPOOL,
    suggested_total_weight,
)
from .move import async_move_spool, move_blocker

_WEIGHT = vol.All(vol.Coerce(float), vol.Range(min=0, max=100000))

LOAD_SCHEMA = vol.Schema({vol.Required("device_id"): cv.string, vol.Required("slot"): cv.entity_id})
DEVICE_SCHEMA = vol.Schema({vol.Required("device_id"): cv.string})
MOVE_SCHEMA = vol.Schema({vol.Required("device_id"): cv.string, vol.Required("box_device_id"): cv.string})
ADD_SCHEMA = vol.Schema(
    {
        vol.Required("box_device_id"): cv.string,
        vol.Required(CONF_MATERIAL): vol.All(cv.string, vol.Length(min=1)),
        vol.Required(CONF_COLOR): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(CONF_MANUFACTURER, default=""): cv.string,
        vol.Optional(CONF_DIAMETER, default=DEFAULT_DIAMETER): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional(CONF_TOTAL_WEIGHT): _WEIGHT,
        vol.Optional("remaining_weight"): _WEIGHT,
    }
)


def _error(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders)


def _identifier(hass: HomeAssistant, device_id: str) -> str | None:
    """The id (subentry id of a spool, entry id of a box) this integration gave a device."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    return next((value for domain, value in device.identifiers if domain == DOMAIN), None)


def find_spool(hass: HomeAssistant, device_id: str) -> tuple[ConfigEntry, ConfigSubentry]:
    """The hub and spool subentry behind a spool device."""
    key = _identifier(hass, device_id)
    for entry in hub_entries(hass):
        subentry = entry.subentries.get(key) if key else None
        if subentry is not None and subentry.subentry_type == SUBENTRY_TYPE_SPOOL:
            return entry, subentry
    raise _error("spool_not_found")


def find_box(hass: HomeAssistant, device_id: str) -> ConfigEntry:
    """The hub behind a box device."""
    key = _identifier(hass, device_id)
    entry = hass.config_entries.async_get_entry(key) if key else None
    if entry is None or entry not in hub_entries(hass):
        raise _error("box_not_found")
    return entry


def _free_slot(hass: HomeAssistant, slot: str, except_subentry_id: str) -> None:
    """A slot holds one spool: whoever was assigned to it before leaves the printer."""
    for entry in hub_entries(hass):
        for subentry in spool_subentries(entry):
            if subentry.subentry_id != except_subentry_id and subentry.data.get(CONF_AMS_SLOT) == slot:
                data = {key: value for key, value in subentry.data.items() if key != CONF_AMS_SLOT}
                hass.config_entries.async_update_subentry(entry, subentry, data=data)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the management services (once, for the whole integration)."""

    async def load_spool(call: ServiceCall) -> None:
        entry, subentry = find_spool(hass, call.data["device_id"])
        slot = call.data["slot"]
        if slot not in slot_entities(hass):
            raise _error("slot_unknown", slot=slot)
        _free_slot(hass, slot, subentry.subentry_id)
        hass.config_entries.async_update_subentry(
            entry, subentry, data={**subentry.data, CONF_AMS_SLOT: slot}
        )

    async def unload_spool(call: ServiceCall) -> None:
        entry, subentry = find_spool(hass, call.data["device_id"])
        data = {key: value for key, value in subentry.data.items() if key != CONF_AMS_SLOT}
        hass.config_entries.async_update_subentry(entry, subentry, data=data)

    async def move_spool(call: ServiceCall) -> None:
        source, subentry = find_spool(hass, call.data["device_id"])
        target = find_box(hass, call.data["box_device_id"])
        if target.entry_id == source.entry_id:
            return
        if (blocker := move_blocker(target)) is not None:
            raise _error(blocker, box=target.title)
        await async_move_spool(
            hass, source, subentry, target, title=subentry.title, data=dict(subentry.data)
        )

    async def add_spool(call: ServiceCall) -> None:
        target = find_box(hass, call.data["box_device_id"])
        if (blocker := move_blocker(target)) is not None:
            raise _error(blocker, box=target.title)
        data: dict[str, Any] = {
            CONF_MATERIAL: call.data[CONF_MATERIAL].strip(),
            CONF_COLOR: call.data[CONF_COLOR].strip(),
            CONF_MANUFACTURER: call.data[CONF_MANUFACTURER].strip(),
            CONF_DIAMETER: call.data[CONF_DIAMETER],
        }
        total = call.data.get(CONF_TOTAL_WEIGHT) or suggested_total_weight(
            data[CONF_MANUFACTURER], data[CONF_MATERIAL]
        )
        remaining = call.data.get("remaining_weight")
        if remaining is not None and remaining > total:
            raise _error("remaining_exceeds_total")
        data[CONF_TOTAL_WEIGHT] = total
        data[CONF_INITIAL_REMAINING_WEIGHT] = total if remaining is None else remaining
        title = (call.data.get("name") or "").strip() or _suggest_name(data)
        hass.config_entries.async_add_subentry(
            target,
            ConfigSubentry(data=data, subentry_type=SUBENTRY_TYPE_SPOOL, title=title, unique_id=None),
        )

    async def remove_spool(call: ServiceCall) -> None:
        entry, subentry = find_spool(hass, call.data["device_id"])
        hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)

    for name, handler, schema in (
        (SERVICE_LOAD_SPOOL, load_spool, LOAD_SCHEMA),
        (SERVICE_UNLOAD_SPOOL, unload_spool, DEVICE_SCHEMA),
        (SERVICE_MOVE_SPOOL, move_spool, MOVE_SCHEMA),
        (SERVICE_ADD_SPOOL, add_spool, ADD_SCHEMA),
        (SERVICE_REMOVE_SPOOL, remove_spool, DEVICE_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema)


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Let the card ask for the choices its add/load dialogs offer."""
    websocket_api.async_register_command(hass, websocket_options)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/options"})
@callback
def websocket_options(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Material/color/manufacturer/diameter choices and the AMS slot sensors."""
    connection.send_result(
        msg["id"],
        {
            "materials": MATERIAL_OPTIONS,
            "colors": COLOR_OPTIONS,
            "manufacturers": MANUFACTURER_OPTIONS,
            "diameters": [option["value"] for option in DIAMETER_OPTIONS],
            "slots": slot_entities(hass),
        },
    )
