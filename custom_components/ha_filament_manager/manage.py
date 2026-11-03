"""Services for managing the inventory (used by the dashboard card, usable in automations).

Spools and boxes are addressed by their id (what the card knows) or by the id
of their Home Assistant device (what the service dialog of Home Assistant
offers): both work.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .ams import slot_entities
from .choices import suggest_name
from .const import (
    CONF_COLOR,
    CONF_DIAMETER,
    CONF_HUMIDITY_DELAY,
    CONF_HUMIDITY_MAX,
    CONF_HUMIDITY_SENSOR,
    CONF_LOW_STOCK_THRESHOLD,
    CONF_MANUFACTURER,
    CONF_MATERIAL,
    CONF_NOTIFY_TARGETS,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_SPOOL_LIMIT,
    CONF_TOTAL_WEIGHT,
    DEFAULT_DIAMETER,
    DOMAIN,
    SERVICE_ADD_BOX,
    SERVICE_ADD_SPOOL,
    SERVICE_LOAD_SPOOL,
    SERVICE_MOVE_SPOOL,
    SERVICE_OPEN_SPOOL,
    SERVICE_REMOVE_BOX,
    SERVICE_REMOVE_SPOOL,
    SERVICE_SET_ALERT_NOTIFICATIONS,
    SERVICE_SET_PRINT_NOTIFICATION,
    SERVICE_TEST_PRINT_NOTIFICATION,
    SERVICE_UNLOAD_SPOOL,
    SERVICE_UPDATE_BOX,
    SERVICE_UPDATE_SPOOL,
    suggested_total_weight,
)
from .runtime import FilamentRuntime, get_runtime
from .store import FilamentError

_WEIGHT = vol.All(vol.Coerce(float), vol.Range(min=0, max=100000))
# A number that may be cleared again (None or "" = not set).
_OPTIONAL_NUMBER = vol.Any(None, "", vol.Coerce(float))
_OPTIONAL_ENTITY = vol.Any(None, "", cv.entity_id)
_ENTITY_LIST = vol.All(cv.ensure_list, [cv.entity_id])

_BOX_SETTINGS = {
    vol.Optional(CONF_HUMIDITY_SENSOR): _OPTIONAL_ENTITY,
    vol.Optional(CONF_HUMIDITY_MAX): _OPTIONAL_NUMBER,
    vol.Optional(CONF_HUMIDITY_DELAY): _OPTIONAL_NUMBER,
    vol.Optional(CONF_SPOOL_LIMIT): vol.Any(None, "", vol.Coerce(int)),
}
_NAME = vol.All(cv.string, vol.Length(min=1))

ADD_BOX_SCHEMA = vol.Schema({vol.Required("name"): _NAME, **_BOX_SETTINGS})
UPDATE_BOX_SCHEMA = vol.Schema({vol.Required("box"): cv.string, vol.Optional("name"): _NAME, **_BOX_SETTINGS})
BOX_SCHEMA = vol.Schema({vol.Required("box"): cv.string})
SPOOL_SCHEMA = vol.Schema({vol.Required("spool"): cv.string})
LOAD_SCHEMA = vol.Schema({vol.Required("spool"): cv.string, vol.Required("slot"): cv.entity_id})
MOVE_SCHEMA = vol.Schema({vol.Required("spool"): cv.string, vol.Required("box"): cv.string})
ADD_SPOOL_SCHEMA = vol.Schema(
    {
        # Without a box the spool is sealed and goes into the stock.
        vol.Optional("box"): cv.string,
        vol.Required(CONF_MATERIAL): _NAME,
        vol.Required(CONF_COLOR): _NAME,
        vol.Required(CONF_MANUFACTURER): _NAME,
        vol.Optional(CONF_DIAMETER, default=DEFAULT_DIAMETER): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional(CONF_TOTAL_WEIGHT): _WEIGHT,
        vol.Optional("remaining_weight"): _WEIGHT,
        vol.Optional(CONF_LOW_STOCK_THRESHOLD): _OPTIONAL_NUMBER,
    }
)
UPDATE_SPOOL_SCHEMA = vol.Schema(
    {
        vol.Required("spool"): cv.string,
        vol.Optional("name"): _NAME,
        vol.Optional(CONF_MATERIAL): _NAME,
        vol.Optional(CONF_COLOR): _NAME,
        vol.Optional(CONF_MANUFACTURER): _NAME,
        vol.Optional(CONF_DIAMETER): cv.string,
        vol.Optional(CONF_TOTAL_WEIGHT): _WEIGHT,
        vol.Optional(CONF_LOW_STOCK_THRESHOLD): _OPTIONAL_NUMBER,
        vol.Optional("ams_sync"): cv.boolean,
        vol.Optional("cloud_spool"): vol.Any(None, "", cv.string),
        vol.Optional("cloud_sync"): cv.boolean,
    }
)


PRINT_NOTIFICATION_SCHEMA = vol.Schema(
    {
        vol.Optional("enabled"): cv.boolean,
        vol.Optional("printer"): vol.Any(None, "", cv.string),
        vol.Optional("targets"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("name"): cv.string,
        vol.Optional("url"): cv.string,
        vol.Optional("show_filament"): cv.boolean,
        vol.Optional("countdown"): cv.boolean,
    }
)
ALERT_NOTIFICATIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NOTIFY_TARGETS): _ENTITY_LIST,
        vol.Optional(CONF_PERSISTENT_NOTIFICATION): cv.boolean,
    }
)
EMPTY_SCHEMA = vol.Schema({})


def _error(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders
    )


def _runtime(hass: HomeAssistant) -> FilamentRuntime:
    if (runtime := get_runtime(hass)) is None:
        raise _error("not_loaded")
    return runtime


def _resolve(hass: HomeAssistant, value: str, known: dict[str, Any], missing_key: str) -> str:
    """An id of the inventory, given directly or as the id of the item's device."""
    if value in known:
        return value
    if (device := dr.async_get(hass).async_get(value)) is not None:
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier in known:
                return identifier
    raise _error(missing_key)


def _guard(action):
    """Run an inventory change, turning its rejection into a translated validation error."""
    try:
        return action()
    except FilamentError as err:
        raise _error(err.key, **err.placeholders) from err


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the management services (once, for the whole integration)."""

    def spool_of(call: ServiceCall) -> tuple[FilamentRuntime, str]:
        runtime = _runtime(hass)
        return runtime, _resolve(hass, call.data["spool"], runtime.manager.spools, "spool_not_found")

    def box_of(call: ServiceCall, runtime: FilamentRuntime, key: str = "box") -> str:
        return _resolve(hass, call.data[key], runtime.manager.boxes, "box_not_found")

    async def load_spool(call: ServiceCall) -> None:
        runtime, spool_id = spool_of(call)
        slot = call.data["slot"]
        if slot not in slot_entities(hass):
            raise _error("slot_unknown", slot=slot)
        _guard(lambda: runtime.manager.assign_slot(spool_id, slot))

    async def unload_spool(call: ServiceCall) -> None:
        runtime, spool_id = spool_of(call)
        _guard(lambda: runtime.manager.assign_slot(spool_id, None))

    async def move_spool(call: ServiceCall) -> None:
        runtime, spool_id = spool_of(call)
        box_id = box_of(call, runtime)
        _guard(lambda: runtime.manager.move_spool(spool_id, box_id))

    async def add_spool(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        data = dict(call.data)
        box_id = box_of(call, runtime) if data.get("box") else None
        manufacturer, material = data[CONF_MANUFACTURER].strip(), data[CONF_MATERIAL].strip()
        total = data.get(CONF_TOTAL_WEIGHT) or suggested_total_weight(manufacturer, material)
        name = (data.get("name") or "").strip() or suggest_name(
            {CONF_MANUFACTURER: manufacturer, CONF_MATERIAL: material, CONF_COLOR: data[CONF_COLOR]}
        )
        details = {
            key: data[key]
            for key in (CONF_DIAMETER, CONF_LOW_STOCK_THRESHOLD)
            if key in data
        }
        _guard(
            lambda: runtime.manager.add_spool(
                name=name,
                material=material,
                color=data[CONF_COLOR],
                manufacturer=manufacturer,
                box_id=box_id,
                sealed=box_id is None,
                total_weight=total,
                remaining_weight=data.get("remaining_weight", total),
                **details,
            )
        )

    async def update_spool(call: ServiceCall) -> None:
        runtime, spool_id = spool_of(call)
        changes = {key: value for key, value in call.data.items() if key != "spool"}
        _guard(lambda: runtime.manager.update_spool(spool_id, **changes))

    async def remove_spool(call: ServiceCall) -> None:
        runtime, spool_id = spool_of(call)
        _guard(lambda: runtime.manager.remove_spool(spool_id))

    async def add_box(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        _guard(lambda: runtime.manager.add_box(**call.data))

    async def update_box(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        box_id = box_of(call, runtime)
        changes = {key: value for key, value in call.data.items() if key != "box"}
        _guard(lambda: runtime.manager.update_box(box_id, **changes))

    async def remove_box(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        box_id = box_of(call, runtime)
        _guard(lambda: runtime.manager.remove_box(box_id))

    async def set_print_notification(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        runtime.manager.set_print_settings(**call.data)

    async def set_alert_notifications(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        runtime.manager.set_alert_settings(
            targets=call.data.get(CONF_NOTIFY_TARGETS), persistent=call.data.get(CONF_PERSISTENT_NOTIFICATION)
        )

    async def test_print_notification(call: ServiceCall) -> None:
        runtime = _runtime(hass)
        if not runtime.manager.print_settings.targets:
            raise _error("no_print_targets")
        await runtime.printing.async_send_test()

    for name, handler, schema in (
        (SERVICE_SET_ALERT_NOTIFICATIONS, set_alert_notifications, ALERT_NOTIFICATIONS_SCHEMA),
        (SERVICE_SET_PRINT_NOTIFICATION, set_print_notification, PRINT_NOTIFICATION_SCHEMA),
        (SERVICE_TEST_PRINT_NOTIFICATION, test_print_notification, EMPTY_SCHEMA),
        (SERVICE_LOAD_SPOOL, load_spool, LOAD_SCHEMA),
        (SERVICE_UNLOAD_SPOOL, unload_spool, SPOOL_SCHEMA),
        (SERVICE_MOVE_SPOOL, move_spool, MOVE_SCHEMA),
        (SERVICE_OPEN_SPOOL, move_spool, MOVE_SCHEMA),
        (SERVICE_ADD_SPOOL, add_spool, ADD_SPOOL_SCHEMA),
        (SERVICE_UPDATE_SPOOL, update_spool, UPDATE_SPOOL_SCHEMA),
        (SERVICE_REMOVE_SPOOL, remove_spool, SPOOL_SCHEMA),
        (SERVICE_ADD_BOX, add_box, ADD_BOX_SCHEMA),
        (SERVICE_UPDATE_BOX, update_box, UPDATE_BOX_SCHEMA),
        (SERVICE_REMOVE_BOX, remove_box, BOX_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema)
