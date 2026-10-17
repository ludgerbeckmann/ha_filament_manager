"""Optional comparison with the Bambu Lab cloud filament library.

Bambu Studio and the Bambu Handy app keep a filament library in the Bambu
cloud. This module reads it (read-only: nothing is ever written back), so a
spool's remaining amount can follow what the cloud knows. The API is
unofficial; if it stops working the integration simply carries on as before
(the last known values stay, the hubs are not affected).

The cloud only answers clients that look like a browser, hence curl_cffi.
The login flow and the endpoints follow the Bambu Filaments integration
(github.com/Timmes123/ha-bambu-filaments, MIT, (c) 2026 Timmes123).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CLOUD_SCAN_MINUTES,
    CONF_CLOUD,
    CONF_CLOUD_REGION,
    CONF_CLOUD_TOKEN,
    DOMAIN,
    SIGNAL_CLOUD_UPDATED,
)

_LOGGER = logging.getLogger(__name__)

IMPERSONATE = "chrome"
TIMEOUT = 20
PAGE_SIZE = 100
MAX_PAGES = 50  # 5000 spools: a misbehaving response can never loop forever


class BambuCloudError(Exception):
    """Base error of the Bambu cloud client."""


class CloudflareBlocked(BambuCloudError):
    """The request was blocked by Cloudflare's bot protection."""


class AuthFailed(BambuCloudError):
    """The login was rejected (bad credentials or an unexpected answer)."""


class AuthExpired(BambuCloudError):
    """The stored token is no longer valid (HTTP 401)."""


class EmailCodeRequired(BambuCloudError):
    """The login needs the code Bambu has just sent by e-mail (or SMS)."""


class CodeIncorrect(BambuCloudError):
    """The verification code was rejected."""


class TfaRequired(BambuCloudError):
    """The login needs a two-factor (TOTP) code."""

    def __init__(self, tfa_key: str) -> None:
        super().__init__("Two-factor code required")
        self.tfa_key = tfa_key


class BambuCloudClient:
    """Blocking client for the filament library endpoints (run it in an executor)."""

    def __init__(self, region: str, token: str | None = None) -> None:
        self._region = region
        self.token = token

    @property
    def _api(self) -> str:
        return "https://api.bambulab.cn" if self._region == "china" else "https://api.bambulab.com"

    @property
    def _web(self) -> str:
        return "https://bambulab.cn" if self._region == "china" else "https://bambulab.com"

    def _request(
        self,
        method: str,
        url: str,
        body: dict | None = None,
        auth: bool = True,
        extra_headers: dict | None = None,
    ):
        from curl_cffi import requests as curl_requests  # noqa: PLC0415 - optional at import time

        headers = dict(extra_headers or {})
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = getattr(curl_requests, method)(
                url, headers=headers, json=body, timeout=TIMEOUT, impersonate=IMPERSONATE
            )
        except Exception as err:
            raise BambuCloudError(f"Connection to the Bambu cloud failed: {err}") from err
        if response.status_code in (403, 429) and "cloudflare" in response.text.lower():
            raise CloudflareBlocked(f"Blocked by Cloudflare (HTTP {response.status_code})")
        # Only a 401 on an authenticated request means the token expired; the
        # login endpoints answer 401 for bad credentials, which callers map themselves.
        if response.status_code == 401 and auth and self.token:
            raise AuthExpired("Bambu cloud token rejected (HTTP 401)")
        return response

    @staticmethod
    def _json(response) -> dict[str, Any]:
        try:
            return response.json()
        except Exception as err:
            raise BambuCloudError(
                f"Invalid (non-JSON) response from the Bambu cloud (HTTP {response.status_code})"
            ) from err

    def login(self, email: str, password: str) -> str:
        """Start a password login; returns the token or raises what is needed next."""
        response = self._request(
            "post",
            f"{self._api}/v1/user-service/user/login",
            body={"account": email, "password": password, "apiError": ""},
            auth=False,
        )
        if response.status_code != 200:
            raise AuthFailed(f"Login failed (HTTP {response.status_code})")
        data = self._json(response)
        if token := data.get("accessToken"):
            self.token = token
            return token
        login_type = data.get("loginType")
        if login_type == "verifyCode":
            # Bambu already sends the code as part of this attempt.
            raise EmailCodeRequired
        if login_type == "tfa":
            raise TfaRequired(data.get("tfaKey", ""))
        raise AuthFailed(f"Unexpected login response type: {login_type}")

    def login_with_code(self, email: str, code: str) -> str:
        """Complete a verification-code login."""
        response = self._request(
            "post",
            f"{self._api}/v1/user-service/user/login",
            body={"account": email, "code": code},
            auth=False,
        )
        if response.status_code == 200 and (token := self._json(response).get("accessToken")):
            self.token = token
            return token
        raise CodeIncorrect(f"Verification code rejected (HTTP {response.status_code})")

    def login_with_tfa(self, tfa_key: str, code: str) -> str:
        """Complete a two-factor login (the token comes back as a cookie)."""
        csrf_response = self._request("get", f"{self._web}/api/csrf", auth=False)
        csrf = csrf_response.cookies.get("bbl_csrf_token")
        if csrf_response.status_code not in (200, 204) or not csrf:
            raise BambuCloudError(f"Could not obtain a CSRF token (HTTP {csrf_response.status_code})")
        response = self._request(
            "post",
            f"{self._web}/api/sign-in/tfa",
            body={"tfaKey": tfa_key, "tfaCode": code},
            auth=False,
            extra_headers={"x-bbl-csrf-token": csrf, "Cookie": f"bbl_csrf_token={csrf}"},
        )
        token = response.cookies.get("token")
        if response.status_code == 200 and token:
            self.token = token
            return token
        raise CodeIncorrect(f"Two-factor code rejected (HTTP {response.status_code})")

    def get_spools(self) -> list[dict[str, Any]]:
        """Fetch the whole filament library (paginated, read-only)."""
        spools: list[dict[str, Any]] = []
        offset = 0
        for _ in range(MAX_PAGES):
            response = self._request(
                "get",
                f"{self._api}/v1/design-user-service/my/filament/v2?offset={offset}&limit={PAGE_SIZE}",
            )
            if response.status_code != 200:
                raise BambuCloudError(f"Fetching the filament library failed (HTTP {response.status_code})")
            data = self._json(response)
            hits = [hit for hit in (data.get("hits") or []) if isinstance(hit, dict)]
            spools.extend(hits)
            total = data.get("total")
            offset += len(hits)
            if not hits or not isinstance(total, int) or offset >= total:
                break
        return spools


@dataclass(frozen=True)
class CloudSpool:
    """One spool of the Bambu cloud filament library."""

    id: int
    rfid: str | None  # the AMS tray uuid for RFID spools
    name: str
    material: str
    color: str
    remaining: int | None  # grams
    total: int | None  # grams

    @property
    def percent(self) -> float | None:
        """Remaining share of the spool in percent."""
        if self.remaining is None or not self.total:
            return None
        return max(0.0, min(100.0, self.remaining * 100 / self.total))

    @property
    def label(self) -> str:
        """Short description for a picker."""
        parts = [self.name]
        if self.material and self.material not in self.name:
            parts.append(self.material)
        text = " · ".join(parts)
        return f"{text} ({self.remaining} g)" if self.remaining is not None else text


# The Bambu apps sometimes name a bulk-added spool "07/29/2026 10:03 added".
_STAMP = re.compile(r"\d{1,4}[./-]\d{1,2}[./-]\d{1,4}.*\d{1,2}:\d{2}|\d{1,2}:\d{2}.*\d{1,4}[./-]\d{1,2}[./-]\d{1,4}")


def _number(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_spool(raw: dict[str, Any]) -> CloudSpool | None:
    """Turn a library entry into a CloudSpool (None for entries without an id)."""
    spool_id = raw.get("id")
    if not isinstance(spool_id, int):
        return None
    display = str(raw.get("displayName") or "").strip()
    if _STAMP.search(display):
        display = ""
    material = str(raw.get("filamentType") or "")
    colors = raw.get("colors") or [raw.get("color")]
    return CloudSpool(
        id=spool_id,
        rfid=str(raw["RFID"]).upper() if raw.get("RFID") else None,
        name=display or str(raw.get("filamentName") or material or "Spool"),
        material=material,
        color=str(next((c for c in colors if c), "")),
        remaining=_number(raw.get("netWeight")),
        total=_number(raw.get("totalNetWeight")),
    )


class CloudCoordinator(DataUpdateCoordinator[dict[int, CloudSpool]]):
    """Polls the cloud library; on trouble the last values are kept."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Bambu cloud",
            update_interval=timedelta(minutes=CLOUD_SCAN_MINUTES),
        )
        self._client = BambuCloudClient(entry.data[CONF_CLOUD_REGION], entry.data.get(CONF_CLOUD_TOKEN))

    async def _async_update_data(self) -> dict[int, CloudSpool]:
        try:
            raw = await self.hass.async_add_executor_job(self._client.get_spools)
        except AuthExpired as err:
            raise ConfigEntryAuthFailed("The Bambu cloud login expired") from err
        except BambuCloudError as err:
            raise UpdateFailed(str(err)) from err
        return {spool.id: spool for item in raw if (spool := parse_spool(item)) is not None}


@dataclass
class CloudRuntimeData:
    """Runtime data of the cloud account's config entry."""

    coordinator: CloudCoordinator


def is_cloud_entry(entry: ConfigEntry) -> bool:
    """True for the Bambu cloud account entry, False for a hub (filament box)."""
    return bool(entry.data.get(CONF_CLOUD))


def hub_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """All hubs (filament boxes), without the cloud account entry."""
    return [entry for entry in hass.config_entries.async_entries(DOMAIN) if not is_cloud_entry(entry)]


def cloud_spools(hass: HomeAssistant) -> dict[int, CloudSpool] | None:
    """The cloud library as last read, or None without a working cloud account."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if is_cloud_entry(entry) and isinstance(runtime, CloudRuntimeData):
            return runtime.coordinator.data
    return None


@callback
def async_announce_updates(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Tell the hubs whenever the cloud library has been read again."""
    runtime: CloudRuntimeData = entry.runtime_data

    @callback
    def _announce() -> None:
        async_dispatcher_send(hass, SIGNAL_CLOUD_UPDATED)

    entry.async_on_unload(runtime.coordinator.async_add_listener(_announce))
    _announce()  # the first read happened before anyone listened
