from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_filament_manager.const import (
    CARD_URL_PATH,
    CONF_BOX,
    CONF_COLOR,
    CONF_DIAMETER,
    CONF_HUMIDITY_MAX,
    CONF_HUMIDITY_SENSOR,
    CONF_INITIAL_REMAINING_WEIGHT,
    CONF_LOW_STOCK_THRESHOLD,
    CONF_MATERIAL,
    CONF_NAME,
    CONF_NOTIFY_TARGETS,
    CONF_PERSISTENT_NOTIFICATION,
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


def _schema_default(schema, key_name: str):
    for key in schema.schema:
        if str(key) == key_name:
            return key.default() if callable(key.default) else key.default
    raise KeyError(key_name)


async def _start_spool_flow(hass: HomeAssistant):
    """Init the config flow and navigate the entry menu to the spool step."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu"
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "spool"})
    assert result["type"] == "form"
    assert result["step_id"] == "spool"
    return result


async def _add_box(hass: HomeAssistant, **extra_options) -> MockConfigEntry:
    """Create a filament box config entry via the config flow."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "box"})
    assert result["step_id"] == "box"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Dry Box 1", **extra_options}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    return result["result"]


async def test_config_flow_suggests_name_and_creates_entry(hass: HomeAssistant) -> None:
    result = await _start_spool_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MATERIAL: "PETG", CONF_COLOR: "Rot", "manufacturer": "Prusament"},
    )
    assert result["type"] == "form"
    assert result["step_id"] == "details"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DIAMETER: "1.75", CONF_TOTAL_WEIGHT: 1000},
    )
    assert result["type"] == "form"
    assert result["step_id"] == "name"
    assert _schema_default(result["data_schema"], "name") == "Prusament PETG Rot"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "New Spool"})
    assert result["type"] == "create_entry"
    assert result["title"] == "New Spool"
    assert result["options"][CONF_INITIAL_REMAINING_WEIGHT] == 1000
    await hass.async_block_till_done()

    assert hass.states.get("sensor.new_spool_material").state == "PETG"


async def test_config_flow_suggests_total_weight_from_material(hass: HomeAssistant) -> None:
    result = await _start_spool_flow(hass)

    # TPU has no manufacturer-specific entry, but a material-only default of
    # 500g (common industry convention for flexible filaments).
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MATERIAL: "TPU", CONF_COLOR: "Schwarz", "manufacturer": ""},
    )
    assert result["step_id"] == "details"
    assert _schema_default(result["data_schema"], CONF_TOTAL_WEIGHT) == 500

    # An unknown material falls back to the generic default.
    result2 = await _start_spool_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        {CONF_MATERIAL: "PLA", CONF_COLOR: "Schwarz", "manufacturer": ""},
    )
    assert _schema_default(result2["data_schema"], CONF_TOTAL_WEIGHT) == 1000


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


async def test_low_stock_alert_not_created_without_threshold(hass: HomeAssistant) -> None:
    await _setup_entry(hass)
    assert hass.states.get("binary_sensor.test_spool_low_stock_alert") is None


async def test_low_stock_alert_tracks_threshold(hass: HomeAssistant) -> None:
    await _setup_entry(hass, **{CONF_LOW_STOCK_THRESHOLD: 20})
    alert_entity = "binary_sensor.test_spool_low_stock_alert"

    state = hass.states.get(alert_entity)
    assert state is not None
    assert state.state == "off"  # 75% remaining, above the 20% threshold

    await hass.services.async_call(
        DOMAIN, "consume_filament", {"entity_id": NUMBER_ENTITY, "amount": 650}, blocking=True
    )
    await hass.async_block_till_done()

    state = hass.states.get(alert_entity)
    assert state.state == "on"  # 10% remaining, below the 20% threshold
    assert state.attributes["remaining_percentage"] == 10.0


async def test_alerts_notify_and_dismiss(hass: HomeAssistant) -> None:
    sent_messages = []

    async def _fake_send_message(call):
        sent_messages.append(dict(call.data))

    hass.services.async_register("notify", "send_message", _fake_send_message)

    from homeassistant.components import persistent_notification as pn
    from homeassistant.helpers.dispatcher import async_dispatcher_connect

    notification_events = []
    async_dispatcher_connect(
        hass,
        pn.SIGNAL_PERSISTENT_NOTIFICATIONS_UPDATED,
        lambda update_type, notifications: notification_events.append((update_type, notifications)),
    )

    hass.states.async_set("sensor.dry_box_humidity", "30")
    await hass.async_block_till_done()

    await _setup_entry(
        hass,
        **{
            CONF_HUMIDITY_SENSOR: "sensor.dry_box_humidity",
            CONF_HUMIDITY_MAX: 40,
            CONF_NOTIFY_TARGETS: ["notify.fake_target"],
            CONF_PERSISTENT_NOTIFICATION: True,
        },
    )

    hass.states.async_set("sensor.dry_box_humidity", "55")
    await hass.async_block_till_done()

    assert len(sent_messages) == 1
    assert sent_messages[0]["entity_id"] == "notify.fake_target"
    assert "55" in sent_messages[0]["message"]

    added = [e for e in notification_events if e[0] == pn.UpdateType.ADDED]
    assert len(added) == 1

    hass.states.async_set("sensor.dry_box_humidity", "30")
    await hass.async_block_till_done()

    # No new push notification on the falling edge, but the persistent
    # notification is cleared.
    assert len(sent_messages) == 1
    removed = [e for e in notification_events if e[0] == pn.UpdateType.REMOVED]
    assert len(removed) == 1


async def test_overview_card_is_served_and_registered(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL

    registered = hass.data[DATA_EXTRA_MODULE_URL]
    assert any(url.startswith(CARD_URL_PATH) for url in registered.urls)

    client = await hass_client()
    resp = await client.get(CARD_URL_PATH)
    assert resp.status == 200
    body = await resp.text()
    assert "customElements.define(\"filament-manager-card\"" in body


async def test_box_creates_humidity_alert(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.box_humidity", "30")
    await hass.async_block_till_done()

    box = await _add_box(hass, **{CONF_HUMIDITY_SENSOR: "sensor.box_humidity", CONF_HUMIDITY_MAX: 40})

    alert_entity = "binary_sensor.dry_box_1_humidity_alert"
    assert hass.states.get(alert_entity).state == "off"

    hass.states.async_set("sensor.box_humidity", "55")
    await hass.async_block_till_done()
    assert hass.states.get(alert_entity).state == "on"

    # A box has no remaining weight, material or color - only its shared
    # humidity alert.
    assert hass.states.get("number.dry_box_1_remaining_weight") is None
    assert box.data == {"entry_type": "box"}


async def test_spool_in_box_uses_box_humidity_not_its_own(hass: HomeAssistant) -> None:
    box = await _add_box(hass, **{CONF_HUMIDITY_SENSOR: "sensor.box_humidity"})

    hass.states.async_set("sensor.spool_own_humidity", "10")
    await hass.async_block_till_done()

    spool_entry = await _setup_entry(
        hass,
        **{
            CONF_BOX: box.entry_id,
            CONF_HUMIDITY_SENSOR: "sensor.spool_own_humidity",
            CONF_HUMIDITY_MAX: 40,
        },
    )

    # The box overrides a spool's own humidity sensor once assigned to it.
    assert hass.states.get("binary_sensor.test_spool_humidity_alert") is None

    from homeassistant.helpers import device_registry as dr

    device_registry = dr.async_get(hass)
    spool_device = device_registry.async_get_device(identifiers={(DOMAIN, spool_entry.entry_id)})
    box_device = device_registry.async_get_device(identifiers={(DOMAIN, box.entry_id)})
    assert spool_device is not None
    assert box_device is not None
    assert spool_device.via_device_id == box_device.id


async def test_box_full_rejects_a_fifth_spool(hass: HomeAssistant) -> None:
    box = await _add_box(hass)

    for i in range(4):
        await _setup_entry(hass, **{CONF_BOX: box.entry_id})

    result = await _start_spool_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MATERIAL: "PLA", CONF_COLOR: "Schwarz", "manufacturer": ""},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DIAMETER: "1.75", CONF_TOTAL_WEIGHT: 1000, CONF_BOX: box.entry_id},
    )
    assert result["type"] == "form"
    assert result["step_id"] == "details"
    assert result["errors"]["base"] == "box_full"
