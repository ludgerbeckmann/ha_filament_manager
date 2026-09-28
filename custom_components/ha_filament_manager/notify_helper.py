"""Shared push / persistent notification helpers for spool alerts.

Used by the humidity and low-stock binary sensors to notify on the
off -> on transition, and to clear the persistent notification again once
the underlying condition resolves (on -> off).
"""
from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import CONF_NOTIFY_TARGETS, CONF_PERSISTENT_NOTIFICATION, DOMAIN


def _notification_id(entry: ConfigEntry, kind: str) -> str:
    return f"{DOMAIN}_{entry.entry_id}_{kind}"


async def async_send_alert(
    hass: HomeAssistant, entry: ConfigEntry, *, kind: str, title: str, message: str
) -> None:
    """Push a notification and/or create a persistent notification for a spool alert."""
    for target in entry.options.get(CONF_NOTIFY_TARGETS) or []:
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": target, "message": message, "title": title},
            blocking=True,
        )

    if entry.options.get(CONF_PERSISTENT_NOTIFICATION):
        persistent_notification.async_create(
            hass, message, title=title, notification_id=_notification_id(entry, kind)
        )


@callback
def async_dismiss_alert(hass: HomeAssistant, entry: ConfigEntry, *, kind: str) -> None:
    """Dismiss a previously created persistent notification, if any."""
    persistent_notification.async_dismiss(hass, _notification_id(entry, kind))


@callback
def async_handle_alert_transition(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    kind: str,
    was_on: bool,
    is_on: bool,
    title: str,
    message: str,
) -> None:
    """Notify on a rising edge (off -> on) and dismiss on a falling edge (on -> off)."""
    if is_on and not was_on:
        hass.async_create_task(async_send_alert(hass, entry, kind=kind, title=title, message=message))
    elif was_on and not is_on:
        async_dismiss_alert(hass, entry, kind=kind)
