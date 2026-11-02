"""Config flow for the Filament Manager integration.

There is one inventory entry (boxes and spools are managed in the dashboard
card, see store.py) and, optionally, one entry for a Bambu cloud account whose
filament library is compared read-only (see cloud.py).
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .cloud import (
    AuthFailed,
    BambuCloudClient,
    BambuCloudError,
    CloudflareBlocked,
    CodeIncorrect,
    EmailCodeRequired,
    TfaRequired,
    is_cloud_entry,
)
from .const import (
    CLOUD_REGIONS,
    CONF_CLOUD,
    CONF_CLOUD_EMAIL,
    CONF_CLOUD_REGION,
    CONF_CLOUD_TOKEN,
    CONF_MAIN,
    DOMAIN,
)
from .migrate import CURRENT_VERSION, MAIN_UNIQUE_ID


class FilamentManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Filament Manager: the inventory, and optionally a Bambu cloud account."""

    VERSION = CURRENT_VERSION

    def __init__(self) -> None:
        self._client: BambuCloudClient | None = None
        self._region = CLOUD_REGIONS[0]
        self._email = ""
        self._tfa_key = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Offer the inventory and - as long as none is connected - the Bambu cloud account."""
        entries = self.hass.config_entries.async_entries(DOMAIN)
        has_cloud = any(is_cloud_entry(entry) for entry in entries)
        has_main = any(not is_cloud_entry(entry) for entry in entries)
        if has_cloud and has_main:
            return self.async_abort(reason="single_instance_allowed")
        if has_main:
            return await self.async_step_cloud()
        if has_cloud:
            return await self.async_step_main()
        return self.async_show_menu(step_id="user", menu_options=["main", "cloud"])

    async def async_step_main(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create the inventory; boxes and spools are added in the dashboard card."""
        if user_input is not None:
            await self.async_set_unique_id(MAIN_UNIQUE_ID)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Filament Manager", data={CONF_MAIN: True})
        return self.async_show_form(step_id="main")

    # --- optional Bambu cloud account (read-only comparison of the filament library) ---

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Log in to the Bambu cloud with region, e-mail and password (the password is not stored)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._region = user_input[CONF_CLOUD_REGION]
            self._email = user_input[CONF_CLOUD_EMAIL].strip()
            self._client = BambuCloudClient(self._region)
            try:
                await self.hass.async_add_executor_job(
                    self._client.login, self._email, user_input["password"]
                )
            except EmailCodeRequired:
                return await self.async_step_cloud_code()
            except TfaRequired as err:
                self._tfa_key = err.tfa_key
                return await self.async_step_cloud_tfa()
            except AuthFailed:
                errors["base"] = "invalid_auth"
            except CloudflareBlocked:
                errors["base"] = "blocked"
            except (BambuCloudError, ImportError):
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish_cloud()

        schema = vol.Schema(
            {
                vol.Required(CONF_CLOUD_REGION, default=self._region): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=CLOUD_REGIONS,
                        translation_key="cloud_region",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_CLOUD_EMAIL, default=self._email): selector.TextSelector(),
                vol.Required("password"): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="cloud", data_schema=schema, errors=errors)

    async def async_step_cloud_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Bambu has sent a verification code by e-mail (or SMS)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    self._client.login_with_code, self._email, user_input["code"].strip()
                )
            except CodeIncorrect:
                errors["base"] = "invalid_code"
            except CloudflareBlocked:
                errors["base"] = "blocked"
            except BambuCloudError:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish_cloud()
        return self.async_show_form(
            step_id="cloud_code",
            data_schema=vol.Schema({vol.Required("code"): selector.TextSelector()}),
            description_placeholders={"email": self._email},
            errors=errors,
        )

    async def async_step_cloud_tfa(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The account uses two-factor authentication."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    self._client.login_with_tfa, self._tfa_key, user_input["code"].strip()
                )
            except CodeIncorrect:
                errors["base"] = "invalid_code"
            except CloudflareBlocked:
                errors["base"] = "blocked"
            except BambuCloudError:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish_cloud()
        return self.async_show_form(
            step_id="cloud_tfa",
            data_schema=vol.Schema({vol.Required("code"): selector.TextSelector()}),
            errors=errors,
        )

    async def _async_finish_cloud(self) -> ConfigFlowResult:
        """The client holds a valid token: create the account entry or refresh its token."""
        token = self._client.token
        if self.source in (SOURCE_REAUTH, SOURCE_RECONFIGURE):
            entry = self._get_reauth_entry() if self.source == SOURCE_REAUTH else self._get_reconfigure_entry()
            return self.async_update_reload_and_abort(entry, data_updates={CONF_CLOUD_TOKEN: token})
        await self.async_set_unique_id(f"cloud-{self._region}-{self._email.lower()}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Bambu Cloud ({self._email})",
            data={
                CONF_CLOUD: True,
                CONF_CLOUD_REGION: self._region,
                CONF_CLOUD_EMAIL: self._email,
                CONF_CLOUD_TOKEN: token,
            },
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """The cloud token has expired: log in again."""
        self._region = entry_data.get(CONF_CLOUD_REGION, self._region)
        self._email = entry_data.get(CONF_CLOUD_EMAIL, "")
        return await self.async_step_cloud()

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The cloud account can log in again; the inventory has nothing to set here."""
        entry = self._get_reconfigure_entry()
        if not is_cloud_entry(entry):
            return self.async_abort(reason="nothing_to_configure")
        self._region = entry.data[CONF_CLOUD_REGION]
        self._email = entry.data[CONF_CLOUD_EMAIL]
        return await self.async_step_cloud()
