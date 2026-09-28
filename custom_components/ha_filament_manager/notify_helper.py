"""Shared push / persistent notification helpers for spool/box alerts.

Used by the humidity and low-stock binary sensors to notify on the
off -> on transition, and to clear the persistent notification again once
the underlying condition resolves (on -> off).
"""
from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback

from .const import CONF_NOTIFY_TARGETS, CONF_PERSISTENT_NOTIFICATION, DOMAIN


def _notification_id(subentry: ConfigSubentry, kind: str) -> str:
    return f"{DOMAIN}_{subentry.subentry_id}_{kind}"


async def async_send_alert(
    hass: HomeAssistant, subentry: ConfigSubentry, *, kind: str, title: str, message: str
) -> None:
    """Push a notification and/or create a persistent notification for an alert."""
    for target in subentry.data.get(CONF_NOTIFY_TARGETS) or []:
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": target, "message": message, "title": title},
            blocking=True,
        )

    if subentry.data.get(CONF_PERSISTENT_NOTIFICATION):
        persistent_notification.async_create(
            hass, message, title=title, notification_id=_notification_id(subentry, kind)
        )


@callback
def async_dismiss_alert(hass: HomeAssistant, subentry: ConfigSubentry, *, kind: str) -> None:
    """Dismiss a previously created persistent notification, if any."""
    persistent_notification.async_dismiss(hass, _notification_id(subentry, kind))


@callback
def async_handle_alert_transition(
    hass: HomeAssistant,
    subentry: ConfigSubentry,
    *,
    kind: str,
    was_on: bool,
    is_on: bool,
    title: str,
    message: str,
) -> None:
    """Notify on a rising edge (off -> on) and dismiss on a falling edge (on -> off)."""
    if is_on and not was_on:
        hass.async_create_task(async_send_alert(hass, subentry, kind=kind, title=title, message=message))
    elif was_on and not is_on:
        async_dismiss_alert(hass, subentry, kind=kind)
