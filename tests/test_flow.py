"""Setting up the integration."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.ha_filament_manager.const import CONF_MAIN, DOMAIN

from .common import setup_inventory
from .test_cloud import setup_cloud


async def test_adding_the_integration_offers_inventory_and_cloud(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu"
    assert result["menu_options"] == ["main", "cloud"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "main"})
    assert result["type"] == "form"
    assert result["step_id"] == "main"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_MAIN: True}
    await hass.async_block_till_done()
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.state.value == "loaded"


async def test_with_the_inventory_set_up_only_the_cloud_is_offered(hass: HomeAssistant) -> None:
    await setup_inventory(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    assert result["step_id"] == "cloud"


async def test_with_the_cloud_set_up_only_the_inventory_is_offered(hass: HomeAssistant) -> None:
    await setup_cloud(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    assert result["step_id"] == "main"


async def test_nothing_more_to_add_when_both_exist(hass: HomeAssistant) -> None:
    await setup_inventory(hass)
    await setup_cloud(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"


async def test_the_inventory_has_nothing_to_reconfigure(hass: HomeAssistant) -> None:
    entry, _ = await setup_inventory(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] == "abort"
    assert result["reason"] == "nothing_to_configure"
