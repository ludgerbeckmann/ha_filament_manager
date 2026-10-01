"""Config flow for the Filament Manager integration.

A config entry is a *hub*, named by the user when it is added (e.g. one hub
per filament box). Several hubs can exist side by side. Every spool and
filament box is then managed as a config *subentry* of a hub (via its
"+ Add" menu and the gear icon on each subentry). A spool can only be
assigned to a box of its own hub.

Creating a spool subentry is split into three steps: identity (material/
color/manufacturer), details (diameter, total weight - suggested from the
identity step - humidity, optionally a filament box), then name (suggested
from the identity step too). Editing an existing spool is a single combined
step. Creating/editing a box is a single step either way (name, optional
humidity sensor/notifications).
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers import selector

from .boxes import box_subentries, spools_in_box
from .const import (
    COLOR_OPTIONS,
    CONF_BOX,
    CONF_COLOR,
    CONF_DIAMETER,
    CONF_HUMIDITY_DELAY,
    CONF_HUMIDITY_MAX,
    CONF_HUMIDITY_SENSOR,
    CONF_INITIAL_REMAINING_WEIGHT,
    CONF_LOW_STOCK_THRESHOLD,
    CONF_MANUFACTURER,
    CONF_MATERIAL,
    CONF_NAME,
    CONF_NOTIFY_TARGETS,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_TOTAL_WEIGHT,
    DEFAULT_DIAMETER,
    DEFAULT_HUB_NAME,
    DEFAULT_MATERIAL,
    DIAMETER_OPTIONS,
    DOMAIN,
    MANUFACTURER_OPTIONS,
    MATERIAL_OPTIONS,
    MAX_SPOOLS_PER_BOX,
    SUBENTRY_TYPE_BOX,
    SUBENTRY_TYPE_SPOOL,
    suggested_humidity_delay,
    suggested_humidity_max,
    suggested_total_weight,
)


def _weight_selector(default_max: float = 100000) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=default_max,
            step=1,
            unit_of_measurement="g",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _select(options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
            custom_value=True,
        )
    )


def _suggest_name(data: dict[str, Any]) -> str:
    """Suggest a spool name built from its manufacturer, material and color."""
    parts = [
        data.get(CONF_MANUFACTURER, "").strip(),
        data.get(CONF_MATERIAL, "").strip(),
        data.get(CONF_COLOR, "").strip(),
    ]
    return " ".join(part for part in parts if part) or "Filamentspule"


def _identity_fields(defaults: dict[str, Any], *, include_name: bool) -> dict[Any, Any]:
    fields: dict[Any, Any] = {}

    if include_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, ""))] = selector.TextSelector()

    fields[
        vol.Required(CONF_MATERIAL, default=defaults.get(CONF_MATERIAL, DEFAULT_MATERIAL))
    ] = _select(MATERIAL_OPTIONS)
    fields[
        vol.Required(CONF_COLOR, default=defaults.get(CONF_COLOR, COLOR_OPTIONS[0]))
    ] = _select(COLOR_OPTIONS)
    fields[
        vol.Optional(CONF_MANUFACTURER, default=defaults.get(CONF_MANUFACTURER, ""))
    ] = _select(MANUFACTURER_OPTIONS)

    return fields


def _box_selector_field(
    entry: ConfigEntry, defaults: dict[str, Any], *, preselect_single: bool = False
) -> dict[Any, Any]:
    """A spool's (optional) filament box assignment - omitted if none exist yet.

    Only boxes of the same hub are offered. With `preselect_single` (when
    adding a spool), a hub's only box is preselected: a hub typically holds
    one box and its spools.
    """
    boxes = box_subentries(entry)
    if not boxes:
        return {}

    valid_ids = {box.subentry_id for box in boxes}
    current = defaults.get(CONF_BOX)
    if current is None and preselect_single and len(boxes) == 1:
        current = boxes[0].subentry_id
    box_kwargs = {"default": current} if current in valid_ids else {}

    return {
        vol.Optional(CONF_BOX, **box_kwargs): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[{"value": box.subentry_id, "label": box.title} for box in boxes],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    }


def _humidity_fields(defaults: dict[str, Any], *, automatic: bool = False) -> dict[Any, Any]:
    """Humidity sensor, limit and alert delay.

    With `automatic` (filament boxes), limit and delay are optional without a
    default: left empty, they follow the most sensitive material in the box.
    A suggested value (not a default) is used so an existing value can be
    cleared again to switch back to automatic.
    """
    fields: dict[Any, Any] = {}

    humidity_sensor_kwargs = (
        {"default": defaults[CONF_HUMIDITY_SENSOR]} if defaults.get(CONF_HUMIDITY_SENSOR) else {}
    )
    fields[vol.Optional(CONF_HUMIDITY_SENSOR, **humidity_sensor_kwargs)] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
    )

    def _key(conf: str, material_default: int):
        if automatic:
            suggested = defaults.get(conf)
            return vol.Optional(
                conf, description={"suggested_value": suggested} if suggested is not None else None
            )
        return vol.Optional(conf, default=defaults.get(conf, material_default))

    material = defaults.get(CONF_MATERIAL)
    fields[_key(CONF_HUMIDITY_MAX, suggested_humidity_max(material))] = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=100, step=1, unit_of_measurement="%", mode=selector.NumberSelectorMode.BOX
        )
    )
    fields[_key(CONF_HUMIDITY_DELAY, suggested_humidity_delay(material))] = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=1440, step=1, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX
        )
    )

    return fields


def _notify_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    fields: dict[Any, Any] = {}

    notify_targets_kwargs = (
        {"default": defaults[CONF_NOTIFY_TARGETS]} if defaults.get(CONF_NOTIFY_TARGETS) else {}
    )
    fields[vol.Optional(CONF_NOTIFY_TARGETS, **notify_targets_kwargs)] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="notify", multiple=True)
    )
    fields[
        vol.Optional(CONF_PERSISTENT_NOTIFICATION, default=defaults.get(CONF_PERSISTENT_NOTIFICATION, False))
    ] = selector.BooleanSelector()

    return fields


def _details_fields(entry: ConfigEntry, defaults: dict[str, Any], *, include_initial: bool) -> dict[Any, Any]:
    fields: dict[Any, Any] = {}

    fields[
        vol.Required(CONF_DIAMETER, default=defaults.get(CONF_DIAMETER, DEFAULT_DIAMETER))
    ] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=DIAMETER_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN)
    )

    default_total_weight = defaults.get(
        CONF_TOTAL_WEIGHT,
        suggested_total_weight(defaults.get(CONF_MANUFACTURER), defaults.get(CONF_MATERIAL)),
    )
    fields[vol.Required(CONF_TOTAL_WEIGHT, default=default_total_weight)] = _weight_selector()

    if include_initial:
        fields[vol.Optional(CONF_INITIAL_REMAINING_WEIGHT)] = _weight_selector()

    fields.update(_box_selector_field(entry, defaults, preselect_single=include_initial))

    # Ignored (falls back to a shared alert) once a filament box is assigned
    # above - kept here as a fallback for spools that aren't in a box.
    fields.update(_humidity_fields(defaults))

    # No default on purpose: presence of a value is what enables the
    # low-stock binary sensor for this spool, mirroring how CONF_HUMIDITY_SENSOR
    # gates the humidity alert above.
    low_stock_kwargs = (
        {"default": defaults[CONF_LOW_STOCK_THRESHOLD]}
        if defaults.get(CONF_LOW_STOCK_THRESHOLD) is not None
        else {}
    )
    fields[vol.Optional(CONF_LOW_STOCK_THRESHOLD, **low_stock_kwargs)] = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=100, step=1, unit_of_measurement="%", mode=selector.NumberSelectorMode.BOX
        )
    )

    fields.update(_notify_fields(defaults))

    return fields


def _box_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    fields: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): selector.TextSelector(),
    }
    fields.update(_humidity_fields(defaults, automatic=True))
    fields.update(_notify_fields(defaults))
    return fields


def _build_reconfigure_schema(entry: ConfigEntry, defaults: dict[str, Any]) -> vol.Schema:
    """Combined identity + details schema, used by the (single-step) spool reconfigure flow."""
    fields = {
        **_identity_fields(defaults, include_name=True),
        **_details_fields(entry, defaults, include_initial=False),
    }
    return vol.Schema(fields)


class FilamentManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Filament Manager hub - just a named container for spools and boxes."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create a hub entry. Spools and boxes are added as subentries afterwards."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip()
            if not name:
                errors["name"] = "name_required"
            else:
                return self.async_create_entry(title=name, data={})

        schema = vol.Schema(
            {vol.Required(CONF_NAME, default=DEFAULT_HUB_NAME): selector.TextSelector()}
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @classmethod
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types this hub supports: spools and filament boxes."""
        return {
            SUBENTRY_TYPE_SPOOL: SpoolSubentryFlowHandler,
            SUBENTRY_TYPE_BOX: BoxSubentryFlowHandler,
        }


class SpoolSubentryFlowHandler(ConfigSubentryFlow):
    """Handle creating or reconfiguring a spool subentry."""

    def __init__(self) -> None:
        self._spool_data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Collect the spool's identity: material, color, manufacturer."""
        if user_input is not None:
            self._spool_data = user_input
            return await self.async_step_details()

        schema = vol.Schema(_identity_fields({}, include_name=False))
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_details(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Collect diameter, total weight (suggested from the identity step) and humidity settings."""
        errors: dict[str, str] = {}
        entry = self._get_entry()

        if user_input is not None:
            total_weight = user_input[CONF_TOTAL_WEIGHT]
            initial_remaining = user_input.pop(CONF_INITIAL_REMAINING_WEIGHT, None)
            if initial_remaining is None:
                initial_remaining = total_weight

            box_id = user_input.get(CONF_BOX)
            if initial_remaining > total_weight:
                errors["base"] = "remaining_exceeds_total"
            elif box_id and len(spools_in_box(entry, box_id)) >= MAX_SPOOLS_PER_BOX:
                errors["base"] = "box_full"
            else:
                user_input[CONF_INITIAL_REMAINING_WEIGHT] = initial_remaining
                self._spool_data = {**self._spool_data, **user_input}
                return await self.async_step_name()

        schema = vol.Schema(_details_fields(entry, self._spool_data, include_initial=True))
        return self.async_show_form(step_id="details", data_schema=schema, errors=errors)

    async def async_step_name(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Confirm the spool's name, pre-filled from the identity step's choices."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip()
            if not name:
                errors["name"] = "name_required"
            else:
                return self.async_create_entry(title=name, data=self._spool_data)

        schema = vol.Schema(
            {vol.Required(CONF_NAME, default=_suggest_name(self._spool_data)): selector.TextSelector()}
        )
        return self.async_show_form(step_id="name", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Edit an existing spool's details in a single combined step."""
        errors: dict[str, str] = {}
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            name = user_input.pop(CONF_NAME, "").strip()
            box_id = user_input.get(CONF_BOX)
            if not name:
                errors["name"] = "name_required"
            elif (
                box_id
                and len(spools_in_box(entry, box_id, exclude_subentry_id=subentry.subentry_id))
                >= MAX_SPOOLS_PER_BOX
            ):
                errors["base"] = "box_full"
            else:
                return self.async_update_and_abort(entry, subentry, title=name, data=user_input)

        defaults = {CONF_NAME: subentry.title, **subentry.data}
        schema = _build_reconfigure_schema(entry, defaults)
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)


class BoxSubentryFlowHandler(ConfigSubentryFlow):
    """Handle creating or reconfiguring a filament box subentry."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Collect a new filament box's name and optional humidity sensor."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input.pop(CONF_NAME, "").strip()
            if not name:
                errors["name"] = "name_required"
            else:
                return self.async_create_entry(title=name, data=user_input)

        schema = vol.Schema(_box_fields({}))
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Edit an existing box's name and humidity settings."""
        errors: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            name = user_input.pop(CONF_NAME, "").strip()
            if not name:
                errors["name"] = "name_required"
            else:
                return self.async_update_and_abort(self._get_entry(), subentry, title=name, data=user_input)

        defaults = {CONF_NAME: subentry.title, **subentry.data}
        schema = vol.Schema(_box_fields(defaults))
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)
