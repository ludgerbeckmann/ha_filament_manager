from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_filament_manager.const import (
    CONF_COLOR,
    CONF_DIAMETER,
    CONF_HUMIDITY_MAX,
    CONF_HUMIDITY_SENSOR,
    CONF_INITIAL_REMAINING_WEIGHT,
    CONF_MATERIAL,
    CONF_TOTAL_WEIGHT,
    DOMAIN,
)

NUMBER_ENTITY = "number.test_spool_remaining_weight"
PERCENT_ENTITY = "sensor.test_spool_remaining"
MATERIAL_ENTITY = "sensor.test_spool_material"
COLOR_ENTITY = "sensor.test_spool_color"


async def _setup_entry(hass: HomeAssistant, **extra_options):
    options = {
        CONF_MATERIAL: "PLA",
        CONF_COLOR: "Black",
        CONF_DIAMETER: "1.75",
        CONF_TOTAL_WEIGHT: 1000,
        CONF_INITIAL_REMAINING_WEIGHT: 750,
        **extra_options,
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Test Spool", options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_expected_entities(hass: HomeAssistant) -> None:
    await _setup_entry(hass)

    number_state = hass.states.get(NUMBER_ENTITY)
    assert number_state is not None
    assert float(number_state.state) == 750

    percent_state = hass.states.get(PERCENT_ENTITY)
    assert percent_state is not None
    assert float(percent_state.state) == 75.0

    assert hass.states.get(MATERIAL_ENTITY).state == "PLA"
    assert hass.states.get(COLOR_ENTITY).state == "Black"

    # No humidity sensor configured -> no binary_sensor entity created.
    assert hass.states.get("binary_sensor.test_spool_humidity_alert") is None


async def test_consume_and_refill_services_update_percentage(hass: HomeAssistant) -> None:
    await _setup_entry(hass)

    await hass.services.async_call(
        DOMAIN, "consume_filament", {"entity_id": NUMBER_ENTITY, "amount": 50}, blocking=True
    )
    await hass.async_block_till_done()

    assert float(hass.states.get(NUMBER_ENTITY).state) == 700
    assert float(hass.states.get(PERCENT_ENTITY).state) == 70.0

    await hass.services.async_call(DOMAIN, "refill_spool", {"entity_id": NUMBER_ENTITY}, blocking=True)
    await hass.async_block_till_done()

    assert float(hass.states.get(NUMBER_ENTITY).state) == 1000
    assert float(hass.states.get(PERCENT_ENTITY).state) == 100.0


async def test_consume_more_than_remaining_clamps_to_zero(hass: HomeAssistant) -> None:
    await _setup_entry(hass)

    await hass.services.async_call(
        DOMAIN, "consume_filament", {"entity_id": NUMBER_ENTITY, "amount": 5000}, blocking=True
    )
    await hass.async_block_till_done()

    assert float(hass.states.get(NUMBER_ENTITY).state) == 0
    assert float(hass.states.get(PERCENT_ENTITY).state) == 0.0


async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "New Spool",
            CONF_MATERIAL: "PETG",
            CONF_COLOR: "Rot",
            "manufacturer": "",
            CONF_DIAMETER: "1.75",
            CONF_TOTAL_WEIGHT: 1000,
        },
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "New Spool"
    assert result["options"][CONF_INITIAL_REMAINING_WEIGHT] == 1000
    await hass.async_block_till_done()

    assert hass.states.get("sensor.new_spool_material").state == "PETG"


async def test_options_flow_updates_material(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "name": "Test Spool",
            CONF_MATERIAL: "ABS",
            CONF_COLOR: "Black",
            "manufacturer": "",
            CONF_DIAMETER: "1.75",
            CONF_TOTAL_WEIGHT: 1000,
        },
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    assert hass.states.get(MATERIAL_ENTITY).state == "ABS"


async def test_humidity_alert_tracks_source_sensor(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.dry_box_humidity", "30")
    await hass.async_block_till_done()

    await _setup_entry(
        hass,
        **{CONF_HUMIDITY_SENSOR: "sensor.dry_box_humidity", CONF_HUMIDITY_MAX: 40},
    )

    alert_entity = "binary_sensor.test_spool_humidity_alert"
    state = hass.states.get(alert_entity)
    assert state is not None
    assert state.state == "off"

    hass.states.async_set("sensor.dry_box_humidity", "55")
    await hass.async_block_till_done()

    state = hass.states.get(alert_entity)
    assert state.state == "on"
    assert state.attributes["current_humidity"] == 55.0
