"""Config flow for the Filament Manager integration.

Every config entry represents one physical spool. Adding a new spool means
adding another instance of this integration; editing one is done through its
options flow (the gear icon on the entry). Creating a spool is split into
three steps: identity (material/color/manufacturer), details (diameter,
total weight - suggested from the identity step - humidity), then name
(suggested from the identity step too).
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector

from .const import (
    COLOR_OPTIONS,
    CONF_COLOR,
    CONF_DIAMETER,
    CONF_HUMIDITY_MAX,
    CONF_HUMIDITY_SENSOR,
    CONF_INITIAL_REMAINING_WEIGHT,
    CONF_MANUFACTURER,
    CONF_MATERIAL,
    CONF_NAME,
    CONF_TOTAL_WEIGHT,
    DEFAULT_DIAMETER,
    DEFAULT_HUMIDITY_MAX,
    DIAMETER_OPTIONS,
    DOMAIN,
    MANUFACTURER_OPTIONS,
    MATERIAL_OPTIONS,
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
        vol.Required(CONF_MATERIAL, default=defaults.get(CONF_MATERIAL, MATERIAL_OPTIONS[0]))
    ] = _select(MATERIAL_OPTIONS)
    fields[
        vol.Required(CONF_COLOR, default=defaults.get(CONF_COLOR, COLOR_OPTIONS[0]))
    ] = _select(COLOR_OPTIONS)
    fields[
        vol.Optional(CONF_MANUFACTURER, default=defaults.get(CONF_MANUFACTURER, ""))
    ] = _select(MANUFACTURER_OPTIONS)

    return fields


def _details_fields(defaults: dict[str, Any], *, include_initial: bool) -> dict[Any, Any]:
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

    humidity_sensor_kwargs = (
        {"default": defaults[CONF_HUMIDITY_SENSOR]} if defaults.get(CONF_HUMIDITY_SENSOR) else {}
    )
    fields[vol.Optional(CONF_HUMIDITY_SENSOR, **humidity_sensor_kwargs)] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
    )
    fields[
        vol.Optional(CONF_HUMIDITY_MAX, default=defaults.get(CONF_HUMIDITY_MAX, DEFAULT_HUMIDITY_MAX))
    ] = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=100, step=1, unit_of_measurement="%", mode=selector.NumberSelectorMode.BOX
        )
    )

    return fields


def _build_schema(defaults: dict[str, Any], *, include_name: bool, include_initial: bool) -> vol.Schema:
    """Combined identity + details schema, used by the (single-step) options flow."""
    fields = {
        **_identity_fields(defaults, include_name=include_name),
        **_details_fields(defaults, include_initial=include_initial),
    }
    return vol.Schema(fields)


class FilamentManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle creating a new spool."""

    VERSION = 1

    def __init__(self) -> None:
        self._spool_data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Collect the spool's identity: material, color, manufacturer."""
        if user_input is not None:
            self._spool_data = user_input
            return await self.async_step_details()

        schema = vol.Schema(_identity_fields({}, include_name=False))
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Collect diameter, total weight (suggested from the identity step) and humidity settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            total_weight = user_input[CONF_TOTAL_WEIGHT]
            initial_remaining = user_input.pop(CONF_INITIAL_REMAINING_WEIGHT, None)
            if initial_remaining is None:
                initial_remaining = total_weight

            if initial_remaining > total_weight:
                errors["base"] = "remaining_exceeds_total"
            else:
                user_input[CONF_INITIAL_REMAINING_WEIGHT] = initial_remaining
                self._spool_data = {**self._spool_data, **user_input}
                return await self.async_step_name()

        schema = vol.Schema(_details_fields(self._spool_data, include_initial=True))
        return self.async_show_form(step_id="details", data_schema=schema, errors=errors)

    async def async_step_name(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm the spool's name, pre-filled from the identity step's choices."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input.get(CONF_NAME, "").strip()
            if not name:
                errors["name"] = "name_required"
            else:
                return self.async_create_entry(title=name, data={}, options=self._spool_data)

        schema = vol.Schema(
            {vol.Required(CONF_NAME, default=_suggest_name(self._spool_data)): selector.TextSelector()}
        )
        return self.async_show_form(step_id="name", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow used to edit an existing spool."""
        return FilamentManagerOptionsFlow()


class FilamentManagerOptionsFlow(OptionsFlow):
    """Handle editing an existing spool's static details."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit the spool's details. Live remaining weight is not editable here."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input.pop(CONF_NAME, "").strip()
            if not name:
                errors["name"] = "name_required"
            else:
                self.hass.config_entries.async_update_entry(self.config_entry, title=name)
                return self.async_create_entry(title="", data=user_input)

        defaults = {CONF_NAME: self.config_entry.title, **self.config_entry.options}
        schema = _build_schema(defaults, include_name=True, include_initial=False)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
