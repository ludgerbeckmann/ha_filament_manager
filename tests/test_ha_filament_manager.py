from types import MappingProxyType

from homeassistant.config_entries import ConfigSubentry, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
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
    CONF_NOTIFY_TARGETS,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_TOTAL_WEIGHT,
    DEFAULT_HUMIDITY_MAX,
    DOMAIN,
    SUBENTRY_TYPE_BOX,
    SUBENTRY_TYPE_SPOOL,
)

NUMBER_ENTITY = "number.test_spool_remaining_weight"
PERCENT_ENTITY = "sensor.test_spool_remaining"
MATERIAL_ENTITY = "sensor.test_spool_material"
COLOR_ENTITY = "sensor.test_spool_color"


def _spool_data(**overrides):
    return {
        CONF_MATERIAL: "PLA",
        CONF_COLOR: "Black",
        CONF_DIAMETER: "1.75",
        CONF_TOTAL_WEIGHT: 1000,
        CONF_INITIAL_REMAINING_WEIGHT: 750,
        **overrides,
    }


def _spool_subentry(title="Test Spool", **overrides) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=_spool_data(**overrides), subentry_type=SUBENTRY_TYPE_SPOOL, title=title, unique_id=None
    )


def _box_subentry(title="Dry Box 1", **overrides) -> ConfigSubentryData:
    return ConfigSubentryData(data=overrides, subentry_type=SUBENTRY_TYPE_BOX, title=title, unique_id=None)


async def _setup_hub(hass: HomeAssistant, subentries_data=()) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Filament Manager", subentries_data=subentries_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _setup_entry(hass: HomeAssistant, **extra_data) -> MockConfigEntry:
    """Set up the hub with a single "Test Spool" subentry."""
    return await _setup_hub(hass, subentries_data=[_spool_subentry(**extra_data)])


def _subentry_by_title(entry: MockConfigEntry, title: str) -> ConfigSubentry:
    return next(s for s in entry.subentries.values() if s.title == title)


def _add_box_subentry(hass: HomeAssistant, entry: MockConfigEntry, title="Dry Box 1", **overrides) -> ConfigSubentry:
    """Add a filament box subentry directly, bypassing the config flow (fixture setup helper)."""
    subentry = ConfigSubentry(
        data=MappingProxyType(overrides), subentry_type=SUBENTRY_TYPE_BOX, title=title, unique_id=None
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    return subentry


def _add_spool_subentry(
    hass: HomeAssistant, entry: MockConfigEntry, title="Test Spool", **overrides
) -> ConfigSubentry:
    """Add a spool subentry directly, bypassing the config flow (fixture setup helper)."""
    subentry = ConfigSubentry(
        data=MappingProxyType(_spool_data(**overrides)),
        subentry_type=SUBENTRY_TYPE_SPOOL,
        title=title,
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    return subentry


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


async def _start_spool_flow(hass: HomeAssistant, entry: MockConfigEntry):
    """Init the spool subentry creation flow."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_SPOOL), context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    return result


async def test_config_flow_suggests_name_and_creates_entry(hass: HomeAssistant) -> None:
    hub = await _setup_hub(hass)
    result = await _start_spool_flow(hass, hub)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_MATERIAL: "PETG", CONF_COLOR: "Rot", "manufacturer": "Prusament"},
    )
    assert result["type"] == "form"
    assert result["step_id"] == "details"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_DIAMETER: "1.75", CONF_TOTAL_WEIGHT: 1000},
    )
    assert result["type"] == "form"
    assert result["step_id"] == "name"
    assert _schema_default(result["data_schema"], "name") == "Prusament PETG Rot"

    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"name": "New Spool"})
    assert result["type"] == "create_entry"
    assert result["title"] == "New Spool"
    assert result["data"][CONF_INITIAL_REMAINING_WEIGHT] == 1000
    await hass.async_block_till_done()

    assert hass.states.get("sensor.new_spool_material").state == "PETG"


async def test_config_flow_suggests_total_weight_from_material(hass: HomeAssistant) -> None:
    hub = await _setup_hub(hass)
    result = await _start_spool_flow(hass, hub)

    # TPU has no manufacturer-specific entry, but a material-only default of
    # 500g (common industry convention for flexible filaments).
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_MATERIAL: "TPU", CONF_COLOR: "Schwarz", "manufacturer": ""},
    )
    assert result["step_id"] == "details"
    assert _schema_default(result["data_schema"], CONF_TOTAL_WEIGHT) == 500

    # An unknown material falls back to the generic default.
    result2 = await _start_spool_flow(hass, hub)
    result2 = await hass.config_entries.subentries.async_configure(
        result2["flow_id"],
        {CONF_MATERIAL: "PLA", CONF_COLOR: "Schwarz", "manufacturer": ""},
    )
    assert _schema_default(result2["data_schema"], CONF_TOTAL_WEIGHT) == 1000


async def test_config_flow_defaults_to_petg(hass: HomeAssistant) -> None:
    hub = await _setup_hub(hass)
    result = await _start_spool_flow(hass, hub)
    assert _schema_default(result["data_schema"], CONF_MATERIAL) == "PETG"


async def test_config_flow_suggests_humidity_max_from_material(hass: HomeAssistant) -> None:
    hub = await _setup_hub(hass)

    # Hygroscopic materials get a much stricter threshold than PLA.
    for material, expected in (("Nylon", 20), ("TPU", 30), ("PETG", 40), ("PLA", 50)):
        result = await _start_spool_flow(hass, hub)
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {CONF_MATERIAL: material, CONF_COLOR: "Schwarz", "manufacturer": ""},
        )
        assert result["step_id"] == "details"
        assert _schema_default(result["data_schema"], CONF_HUMIDITY_MAX) == expected

    # Unknown materials fall back to the generic default.
    result = await _start_spool_flow(hass, hub)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_MATERIAL: "Sonstiges", CONF_COLOR: "Schwarz", "manufacturer": ""},
    )
    assert _schema_default(result["data_schema"], CONF_HUMIDITY_MAX) == DEFAULT_HUMIDITY_MAX


async def test_reconfigure_flow_updates_material(hass: HomeAssistant) -> None:
    entry = await _setup_entry(hass)
    subentry = _subentry_by_title(entry, "Test Spool")

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_SPOOL),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    assert result["type"] == "form"

    result = await hass.config_entries.subentries.async_configure(
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
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
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

    entry = await _setup_hub(
        hass,
        subentries_data=[_box_subentry(**{CONF_HUMIDITY_SENSOR: "sensor.box_humidity", CONF_HUMIDITY_MAX: 40})],
    )

    alert_entity = "binary_sensor.dry_box_1_humidity_alert"
    assert hass.states.get(alert_entity).state == "off"

    hass.states.async_set("sensor.box_humidity", "55")
    await hass.async_block_till_done()
    assert hass.states.get(alert_entity).state == "on"

    # A box has no remaining weight, material or color - only its shared
    # humidity alert.
    assert hass.states.get("number.dry_box_1_remaining_weight") is None
    box = _subentry_by_title(entry, "Dry Box 1")
    assert box.subentry_type == SUBENTRY_TYPE_BOX


async def test_spool_in_box_uses_box_humidity_not_its_own(hass: HomeAssistant) -> None:
    entry = await _setup_hub(hass)
    box = _add_box_subentry(hass, entry, **{CONF_HUMIDITY_SENSOR: "sensor.box_humidity"})
    await hass.async_block_till_done()

    hass.states.async_set("sensor.spool_own_humidity", "10")
    await hass.async_block_till_done()

    spool = _add_spool_subentry(
        hass,
        entry,
        **{
            CONF_BOX: box.subentry_id,
            CONF_HUMIDITY_SENSOR: "sensor.spool_own_humidity",
            CONF_HUMIDITY_MAX: 40,
        },
    )
    await hass.async_block_till_done()

    # The box overrides a spool's own humidity sensor once assigned to it.
    assert hass.states.get("binary_sensor.test_spool_humidity_alert") is None

    device_registry = dr.async_get(hass)
    spool_device = device_registry.async_get_device(identifiers={(DOMAIN, spool.subentry_id)})
    box_device = device_registry.async_get_device(identifiers={(DOMAIN, box.subentry_id)})
    assert spool_device is not None
    assert box_device is not None
    assert spool_device.via_device_id == box_device.id


async def test_assigning_a_box_removes_the_spools_own_stale_humidity_entity(hass: HomeAssistant) -> None:
    """A spool's own humidity alert must not linger as a stale registry entry.

    Otherwise it would keep showing up (as an "unavailable" ghost) on the
    overview card even though the box now owns humidity monitoring for it.
    """
    hass.states.async_set("sensor.spool_own_humidity", "10")
    await hass.async_block_till_done()

    entry = await _setup_entry(hass, **{CONF_HUMIDITY_SENSOR: "sensor.spool_own_humidity"})
    spool = _subentry_by_title(entry, "Test Spool")

    registry = er.async_get(hass)
    alert_entity = "binary_sensor.test_spool_humidity_alert"
    assert registry.async_get(alert_entity) is not None

    box = _add_box_subentry(hass, entry)
    await hass.async_block_till_done()

    hass.config_entries.async_update_subentry(entry, spool, data={**spool.data, CONF_BOX: box.subentry_id})
    await hass.async_block_till_done()

    assert registry.async_get(alert_entity) is None
    assert hass.states.get(alert_entity) is None


async def test_box_full_rejects_a_fifth_spool(hass: HomeAssistant) -> None:
    entry = await _setup_hub(hass)
    box = _add_box_subentry(hass, entry)
    await hass.async_block_till_done()

    for i in range(4):
        _add_spool_subentry(hass, entry, title=f"Spool {i}", **{CONF_BOX: box.subentry_id})
    await hass.async_block_till_done()

    result = await _start_spool_flow(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_MATERIAL: "PLA", CONF_COLOR: "Schwarz", "manufacturer": ""},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_DIAMETER: "1.75", CONF_TOTAL_WEIGHT: 1000, CONF_BOX: box.subentry_id},
    )
    assert result["type"] == "form"
    assert result["step_id"] == "details"
    assert result["errors"]["base"] == "box_full"
