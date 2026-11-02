"""The optional, read-only comparison with the Bambu cloud filament library."""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_filament_manager.cloud import (
    AuthExpired,
    BambuCloudClient,
    BambuCloudError,
    CloudflareBlocked,
    CodeIncorrect,
    EmailCodeRequired,
    cloud_spools,
    parse_spool,
)
from custom_components.ha_filament_manager.const import (
    CONF_CLOUD,
    CONF_CLOUD_EMAIL,
    CONF_CLOUD_REGION,
    CONF_CLOUD_TOKEN,
    DOMAIN,
)

from .common import NUMBER, setup_with_spool
from .test_ams import RFID_A, set_slot, setup_ams_spool

CLOUD_LIBRARY = [
    {
        "id": 11,
        "RFID": RFID_A.lower(),
        "filamentName": "PLA Basic",
        "filamentType": "PLA",
        "color": "#161616FF",
        "netWeight": 640,
        "totalNetWeight": 1000,
    },
    {
        "id": 12,
        "RFID": "",
        "filamentName": "PETG HF",
        "filamentType": "PETG",
        "displayName": "07/29/2026 10:03 added",
        "netWeight": 300,
        "totalNetWeight": 1000,
    },
]


def library(**remaining) -> list[dict]:
    """The cloud library, with other remaining weights (by cloud id) where given."""
    return [{**spool, "netWeight": remaining.get(str(spool["id"]), spool["netWeight"])} for spool in CLOUD_LIBRARY]


async def setup_cloud(hass: HomeAssistant, data=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bambu Cloud (me@example.com)",
        unique_id="cloud-global-me@example.com",
        version=2,
        data={
            CONF_CLOUD: True,
            CONF_CLOUD_REGION: "global",
            CONF_CLOUD_EMAIL: "me@example.com",
            CONF_CLOUD_TOKEN: "token",
        },
    )
    entry.add_to_hass(hass)
    with patch.object(BambuCloudClient, "get_spools", return_value=data or CLOUD_LIBRARY):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def refresh(hass: HomeAssistant, cloud: MockConfigEntry, data) -> None:
    with patch.object(BambuCloudClient, "get_spools", return_value=data):
        await cloud.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()


async def test_cloud_spools_are_parsed_and_stamp_names_ignored() -> None:
    plain, stamped = (parse_spool(raw) for raw in CLOUD_LIBRARY)
    assert (plain.name, plain.rfid, plain.percent) == ("PLA Basic", RFID_A, 64)
    assert stamped.name == "PETG HF"  # not the auto-generated "07/29/2026 10:03 added"
    assert parse_spool({"filamentName": "no id"}) is None


async def test_chosen_cloud_spool_sets_the_remaining_weight_once_then_follows_changes(hass: HomeAssistant) -> None:
    cloud = await setup_cloud(hass)
    await setup_with_spool(hass, spool={"cloud_spool": "11"})

    # First match: adopt the cloud's 64 % of this spool's 1000 g.
    assert float(hass.states.get(NUMBER).state) == 640
    assert hass.states.get(NUMBER).attributes["cloud_spool"] == "PLA Basic"

    # A value set by hand stays while the cloud reports the same as before ...
    await hass.services.async_call("number", "set_value", {"entity_id": NUMBER, "value": 500}, blocking=True)
    await refresh(hass, cloud, library())
    assert float(hass.states.get(NUMBER).state) == 500

    # ... and follows the cloud again once it changes.
    await refresh(hass, cloud, library(**{"11": 250}))
    assert float(hass.states.get(NUMBER).state) == 250


async def test_cloud_spool_is_matched_by_the_rfid_learned_from_the_ams(hass: HomeAssistant) -> None:
    set_slot(hass, rfid=RFID_A)
    await setup_cloud(hass)
    await setup_ams_spool(hass)  # no cloud spool picked: automatic

    assert hass.states.get(NUMBER).attributes["cloud_spool_id"] == 11
    assert float(hass.states.get(NUMBER).state) == 640


async def test_choosing_a_cloud_spool_later_matches_it(hass: HomeAssistant) -> None:
    await setup_cloud(hass)
    entry, manager = await setup_with_spool(hass)
    assert "cloud_spool" not in hass.states.get(NUMBER).attributes

    (spool,) = manager.spools.values()
    manager.update_spool(spool.id, cloud_spool="12")
    await hass.async_block_till_done()
    assert hass.states.get(NUMBER).attributes["cloud_spool"] == "PETG HF"
    assert float(hass.states.get(NUMBER).state) == 300

    manager.update_spool(spool.id, cloud_spool="")  # back to automatic: nothing to match without an RFID
    await hass.async_block_till_done()
    assert "cloud_spool" not in hass.states.get(NUMBER).attributes


async def test_sync_off_matches_but_does_not_follow(hass: HomeAssistant) -> None:
    await setup_cloud(hass)
    await setup_with_spool(hass, spool={"cloud_spool": "11", "cloud_sync": False})
    assert float(hass.states.get(NUMBER).state) == 750  # the initial value
    assert hass.states.get(NUMBER).attributes["cloud_spool_id"] == 11


async def test_inventory_carries_on_when_the_cloud_does_not_answer(hass: HomeAssistant) -> None:
    cloud = MockConfigEntry(
        domain=DOMAIN,
        unique_id="cloud-global-me@example.com",
        version=2,
        data={CONF_CLOUD: True, CONF_CLOUD_REGION: "global", CONF_CLOUD_EMAIL: "x", CONF_CLOUD_TOKEN: "t"},
    )
    cloud.add_to_hass(hass)
    with patch.object(BambuCloudClient, "get_spools", side_effect=BambuCloudError("down")):
        assert not await hass.config_entries.async_setup(cloud.entry_id)
    await setup_with_spool(hass, spool={"cloud_spool": "11"})
    assert float(hass.states.get(NUMBER).state) == 750
    assert "cloud_spool" not in hass.states.get(NUMBER).attributes
    assert cloud_spools(hass) is None


async def test_expired_cloud_login_asks_for_a_new_login(hass: HomeAssistant) -> None:
    cloud = MockConfigEntry(
        domain=DOMAIN,
        unique_id="cloud-global-me@example.com",
        version=2,
        data={CONF_CLOUD: True, CONF_CLOUD_REGION: "global", CONF_CLOUD_EMAIL: "x", CONF_CLOUD_TOKEN: "t"},
    )
    cloud.add_to_hass(hass)
    with patch.object(BambuCloudClient, "get_spools", side_effect=AuthExpired):
        await hass.config_entries.async_setup(cloud.entry_id)
        await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_cloud_login_with_an_emailed_code_creates_the_account_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu"
    assert result["menu_options"] == ["main", "cloud"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "cloud"})
    assert result["step_id"] == "cloud"

    user = {CONF_CLOUD_REGION: "global", CONF_CLOUD_EMAIL: "me@example.com", "password": "secret"}
    with patch.object(BambuCloudClient, "login", side_effect=EmailCodeRequired):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user)
    assert result["step_id"] == "cloud_code"

    with patch.object(BambuCloudClient, "login_with_code", side_effect=CodeIncorrect):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "000000"})
    assert result["errors"] == {"base": "invalid_code"}

    def _accept(self, email, code):
        self.token = "fresh-token"
        return self.token

    with (
        patch.object(BambuCloudClient, "login_with_code", _accept),
        patch.object(BambuCloudClient, "get_spools", return_value=CLOUD_LIBRARY),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123456"})
        await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"] == {
        CONF_CLOUD: True,
        CONF_CLOUD_REGION: "global",
        CONF_CLOUD_EMAIL: "me@example.com",
        CONF_CLOUD_TOKEN: "fresh-token",
    }
    assert "password" not in result["data"]


async def test_cloud_login_reports_unreachable_cloud(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "cloud"})
    user = {CONF_CLOUD_REGION: "global", CONF_CLOUD_EMAIL: "me@example.com", "password": "secret"}
    with patch.object(BambuCloudClient, "login", side_effect=BambuCloudError("down")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user)
    assert result["errors"] == {"base": "cannot_connect"}


class _FakeResponse:
    def __init__(self, status=200, body=None, text="", cookies=None):
        self.status_code, self._body, self.text, self.cookies = status, body, text, cookies or {}

    def json(self):
        return self._body


def _fake_curl(monkeypatch, handler):
    """Stand in for curl_cffi (not needed to run the tests): handler(method, url, **kwargs)."""
    requests = types.SimpleNamespace(
        get=lambda url, **kw: handler("get", url, **kw), post=lambda url, **kw: handler("post", url, **kw)
    )
    monkeypatch.setitem(sys.modules, "curl_cffi", types.SimpleNamespace(requests=requests))
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", requests)


def test_client_reads_every_page_of_the_library_with_the_token(monkeypatch) -> None:
    calls = []

    def handler(method, url, **kwargs):
        calls.append((url, kwargs["headers"].get("Authorization")))
        offset = int(url.split("offset=")[1].split("&")[0])
        return _FakeResponse(body={"total": 3, "hits": [{"id": i} for i in range(offset, min(offset + 2, 3))]})

    _fake_curl(monkeypatch, handler)
    monkeypatch.setattr("custom_components.ha_filament_manager.cloud.PAGE_SIZE", 2)
    spools = BambuCloudClient("global", "tok").get_spools()
    assert [spool["id"] for spool in spools] == [0, 1, 2]
    assert len(calls) == 2 and all(auth == "Bearer tok" for _, auth in calls)


def test_client_maps_login_answers_to_errors(monkeypatch) -> None:
    answers = iter(
        [
            _FakeResponse(body={"loginType": "verifyCode"}),
            _FakeResponse(403, text="Attention Required! | Cloudflare"),
            _FakeResponse(401),
        ]
    )
    _fake_curl(monkeypatch, lambda method, url, **kw: next(answers))
    client = BambuCloudClient("global")
    for expected in (EmailCodeRequired, CloudflareBlocked):
        try:
            client.login("a@b.c", "pw")
            raise AssertionError(f"expected {expected.__name__}")
        except expected:
            pass
    try:
        BambuCloudClient("global", "old").get_spools()
        raise AssertionError("expected AuthExpired")
    except AuthExpired:
        pass
