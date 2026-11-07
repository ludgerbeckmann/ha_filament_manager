"""Websocket API of the dashboard card: a live snapshot of the inventory, choices and suggestions."""
from __future__ import annotations

import json
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .ams import ams_units, slot_entities
from .cloud import cloud_spools
from .const import (
    COLOR_OPTIONS,
    CONF_COLOR,
    CONF_MANUFACTURER,
    CONF_MATERIAL,
    CONF_VARIANT,
    DEFAULT_MATERIAL,
    DIAMETER_OPTIONS,
    DOMAIN,
    MANUFACTURER_OPTIONS,
    MATERIAL_OPTIONS,
    SIGNAL_SNAPSHOT_DIRTY,
    VARIANT_OPTIONS,
    suggested_total_weight,
)
from .choices import sorted_options, suggest_name
from .printing import notify_services, printer_entities, printers
from .runtime import FilamentRuntime, get_runtime


def build_snapshot(hass: HomeAssistant, runtime: FilamentRuntime) -> dict[str, Any]:
    """Everything the card shows: boxes, spools (with the entities to open) and the AMS slots."""
    manager = runtime.manager
    registry = er.async_get(hass)

    def entity_id(domain: str, unique_id: str) -> str | None:
        return registry.async_get_entity_id(domain, DOMAIN, unique_id)

    boxes = []
    for box in manager.boxes.values():
        threshold, delay = manager.box_limits(box.id)
        boxes.append(
            {
                "id": box.id,
                "name": box.name,
                "humidity_sensor": box.humidity_sensor,
                "temperature_sensor": box.temperature_sensor,
                "humidity_max": box.humidity_max,
                "humidity_delay": box.humidity_delay,
                "effective_humidity_max": threshold,
                "effective_humidity_delay": delay,
                "spool_limit": box.spool_limit,
                "count": len(manager.spools_in(box.id)),
                "alert_entity": entity_id("binary_sensor", f"{box.id}_humidity_alert"),
                "count_entity": entity_id("sensor", f"{box.id}_spool_count"),
            }
        )

    spools = []
    for spool in manager.spools.values():
        ams = runtime.ams.states.get(spool.id)
        match = runtime.cloud.matches.get(spool.id)
        spools.append(
            {
                "id": spool.id,
                "name": spool.name,
                "material": spool.material,
                "variant": spool.variant,
                "color": spool.color,
                "manufacturer": spool.manufacturer,
                "diameter": spool.diameter,
                "total_weight": spool.total_weight,
                "remaining_weight": spool.remaining_weight,
                "percent": round(spool.remaining_weight / spool.total_weight * 100, 1)
                if spool.total_weight
                else None,
                "box_id": spool.box_id,
                "sealed": spool.sealed,
                "ams_slot": spool.ams_slot,
                "ams_sync": spool.ams_sync,
                "in_printer": bool(ams and ams.in_printer),
                "cloud_spool": spool.cloud_spool,
                "cloud_sync": spool.cloud_sync,
                "cloud_match": match.name if match else None,
                "low_stock_threshold": spool.low_stock_threshold,
                "entity_id": entity_id("number", f"{spool.id}_remaining_weight"),
            }
        )
    library = cloud_spools(hass)
    cloud = (
        sorted(({"id": str(item.id), "label": item.label} for item in library.values()), key=lambda i: i["label"].casefold())
        if library
        else None
    )
    settings = manager.print_settings
    print_notification = {
        "enabled": settings.enabled,
        "printer": settings.printer,
        "targets": settings.targets,
        "name": settings.name,
        "url": settings.url,
        "show_filament": settings.show_filament,
        "countdown": settings.countdown,
        "printers": [{"serial": printer.serial, "name": printer.name} for printer in printers(hass)],
        "notify_services": notify_services(hass),
    }
    return {
        "boxes": boxes,
        "spools": spools,
        "slots": slot_entities(hass),
        "ams": ams_units(hass),
        "printers": [
            {"serial": printer.serial, "name": printer.name, "entities": printer_entities(hass, printer.serial)}
            for printer in printers(hass)
        ],
        "cloud": cloud,
        "print_notification": print_notification,
        "alerts": {
            "targets": manager.alert_settings.targets,
            "persistent": manager.alert_settings.persistent,
        },
    }


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the commands (once, for the whole integration)."""
    websocket_api.async_register_command(hass, websocket_subscribe)
    websocket_api.async_register_command(hass, websocket_options)
    websocket_api.async_register_command(hass, websocket_suggest)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def websocket_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Send the inventory now and again after every change."""
    runtime = get_runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Filament Manager is not set up")
        return

    last: list[str] = []

    @callback
    def _send() -> None:
        snapshot = build_snapshot(hass, runtime)
        encoded = json.dumps(snapshot, sort_keys=True, default=str)
        if last and last[0] == encoded:
            return  # nothing the card shows has changed
        last[:] = [encoded]
        connection.send_message(websocket_api.event_message(msg["id"], snapshot))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_SNAPSHOT_DIRTY, _send)
    connection.send_result(msg["id"])
    _send()


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/options"})
@callback
def websocket_options(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Material/color/manufacturer/diameter choices, sorted like the old setup dialog."""
    connection.send_result(
        msg["id"],
        {
            "materials": sorted_options(MATERIAL_OPTIONS),
            "variants": sorted_options(VARIANT_OPTIONS),
            "colors": sorted_options(COLOR_OPTIONS),
            "manufacturers": sorted_options(MANUFACTURER_OPTIONS),
            "diameters": [option["value"] for option in DIAMETER_OPTIONS],
            "default_material": DEFAULT_MATERIAL,
            "default_color": COLOR_OPTIONS[0],
            # What the add dialog starts with (its first manufacturer), so it can open complete.
            "default_suggestion": _suggestion(
                DEFAULT_MATERIAL, COLOR_OPTIONS[0], sorted_options(MANUFACTURER_OPTIONS)[0]
            ),
        },
    )


def _suggestion(material: str, color: str, manufacturer: str, variant: str = "") -> dict[str, Any]:
    data = {
        CONF_MATERIAL: material.strip(),
        CONF_VARIANT: variant.strip(),
        CONF_COLOR: color.strip(),
        CONF_MANUFACTURER: manufacturer.strip(),
    }
    return {
        "name": suggest_name(data),
        "total_weight": suggested_total_weight(data[CONF_MANUFACTURER], data[CONF_MATERIAL]),
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/suggest",
        vol.Required(CONF_MATERIAL): cv.string,
        vol.Required(CONF_COLOR): cv.string,
        vol.Required(CONF_MANUFACTURER): cv.string,
        vol.Optional(CONF_VARIANT, default=""): cv.string,
    }
)
@callback
def websocket_suggest(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The name and total weight suggested for these choices."""
    connection.send_result(msg["id"], _suggestion(msg[CONF_MATERIAL], msg[CONF_COLOR], msg[CONF_MANUFACTURER], msg[CONF_VARIANT]))
