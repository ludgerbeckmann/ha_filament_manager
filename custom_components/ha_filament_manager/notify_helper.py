"""Shared push / persistent notification helpers for spool/box alerts.

Used by the humidity and low-stock binary sensors to notify on the
off -> on transition, and to clear the persistent notification again once
the underlying condition resolves (on -> off).
"""
from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .store import Box, Spool

# An alert belongs either to a spool or to a box.
AlertOwner = Spool | Box


def _notification_id(owner: AlertOwner, kind: str) -> str:
    return f"{DOMAIN}_{owner.id}_{kind}"


async def async_send_alert(hass: HomeAssistant, owner: AlertOwner, *, kind: str, title: str, message: str) -> None:
    """Push a notification and/or create a persistent notification for an alert."""
    for target in owner.notify_targets or []:
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": target, "message": message, "title": title},
            blocking=True,
        )

    if owner.persistent_notification:
        persistent_notification.async_create(
            hass, message, title=title, notification_id=_notification_id(owner, kind)
        )


@callback
def async_dismiss_alert(hass: HomeAssistant, owner: AlertOwner, *, kind: str) -> None:
    """Dismiss a previously created persistent notification, if any."""
    persistent_notification.async_dismiss(hass, _notification_id(owner, kind))


@callback
def async_handle_alert_transition(
    hass: HomeAssistant,
    owner: AlertOwner,
    *,
    kind: str,
    was_on: bool,
    is_on: bool,
    title: str,
    message: str,
) -> None:
    """Notify on a rising edge (off -> on) and dismiss on a falling edge (on -> off)."""
    if is_on and not was_on:
        hass.async_create_task(async_send_alert(hass, owner, kind=kind, title=title, message=message))
    elif was_on and not is_on:
        async_dismiss_alert(hass, owner, kind=kind)
