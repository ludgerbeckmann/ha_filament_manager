from datetime import timedelta
from types import MappingProxyType

from homeassistant.components import persistent_notification as pn
from homeassistant.config_entries import ConfigSubentry, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.ha_filament_manager.const import (
    CARD_URL_PATH,
    CONF_COLOR,
    CONF_DIAMETER,
    CONF_HUMIDITY_DELAY,
    CONF_HUMIDITY_MAX,
    CONF_HUMIDITY_SENSOR,
    CONF_INITIAL_REMAINING_WEIGHT,
    CONF_LOW_STOCK_THRESHOLD,
    CONF_MATERIAL,
    CONF_NOTIFY_TARGETS,
    CONF_PERSISTENT_NOTIFICATION,
    CONF_SPOOL_LIMIT,
    CONF_TOTAL_WEIGHT,
    DEFAULT_HUMIDITY_DELAY,
    DEFAULT_HUMIDITY_MAX,
    DOMAIN,
    SUBENTRY_TYPE_BOX,
    SUBENTRY_TYPE_SPOOL,
)

HUB_TITLE = "Test Box"
NUMBER_ENTITY = "number.test_spool_remaining_weight"
PERCENT_ENTITY = "sensor.test_spool_remaining"
MATERIAL_ENTITY = "sensor.test_spool_material"
COLOR_ENTITY = "sensor.test_spool_color"
SPOOL_COUNT_ENTITY = "sensor.test_box_spools"
HUMIDITY_ALERT = "binary_sensor.test_box_humidity_alert"


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


async def _setup_hub(
    hass: HomeAssistant, subentries_data=(), title: str = HUB_TITLE, **hub_data
) -> MockConfigEntry:
    """Set up a hub (= filament box) with the given settings and spool subentries."""
    entry = MockConfigEntry(domain=DOMAIN, title=title, data=hub_data, subentries_data=subentries_data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _setup_entry(hass: HomeAssistant, **spool_data) -> MockConfigEntry:
    """Set up a hub with a single "Test Spool" subentry."""
    return await _setup_hub(hass, subentries_data=[_spool_subentry(**spool_data)])


def _subentry_by_title(entry: MockConfigEntry, title: str) -> ConfigSubentry:
    return next(s for s in entry.subentries.values() if s.title == title)


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


def _schema_default(schema, key_name: str):
    for key in schema.schema:
        if str(key) == key_name:
            return key.default() if callable(key.default) else key.default
    raise KeyError(key_name)


def _schema_options(schema, key_name: str) -> list[str]:
    key = next(key for key in schema.schema if str(key) == key_name)
    return [
        option if isinstance(option, str) else option["value"]
        for option in schema.schema[key].config["options"]
    ]


async def _start_spool_flow(hass: HomeAssistant, entry: MockConfigEntry):
    """Init the spool subentry creation flow."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_SPOOL), context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    return result


# --- spool entities and services -------------------------------------------


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

    # No humidity sensor configured on the hub -> no humidity alert.
    assert hass.states.get(HUMIDITY_ALERT) is None


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


# --- spool flows -------------------------------------------------------------


async def test_spool_flow_suggests_name_and_creates_entry(hass: HomeAssistant) -> None:
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


async def test_spool_flow_suggests_total_weight_from_material(hass: HomeAssistant) -> None:
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


async def test_spool_flow_defaults_to_petg_and_sorts_dropdowns_alphabetically(hass: HomeAssistant) -> None:
    hub = await _setup_hub(hass)
    result = await _start_spool_flow(hass, hub)
    schema = result["data_schema"]

    assert _schema_default(schema, CONF_MATERIAL) == "PETG"

    # Alphabetical, with the catch-all entry always last.
    materials = _schema_options(schema, CONF_MATERIAL)
    assert materials == ["ABS", "ASA", "HIPS", "Nylon", "PC", "PETG", "PLA", "PVA", "TPU", "Sonstiges"]
    colors = _schema_options(schema, CONF_COLOR)
    assert colors[:3] == ["Beige", "Blau", "Braun"]
    assert colors[-1] == "Sonstige"
    assert colors[:-1] == sorted(colors[:-1], key=str.casefold)
    manufacturers = _schema_options(schema, "manufacturer")
    assert manufacturers[0] == "3DJake"
    assert manufacturers[-1] == "Sonstiges"
    assert manufacturers[:-1] == sorted(manufacturers[:-1], key=str.casefold)


async def test_spool_reconfigure_flow_updates_material(hass: HomeAssistant) -> None:
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


async def test_spool_limit_blocks_adding_more_spools(hass: HomeAssistant) -> None:
    hub = await _setup_hub(
        hass,
        subentries_data=[_spool_subentry("Spool 1"), _spool_subentry("Spool 2")],
        **{CONF_SPOOL_LIMIT: 2},
    )

    result = await hass.config_entries.subentries.async_init(
        (hub.entry_id, SUBENTRY_TYPE_SPOOL), context={"source": "user"}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "box_full"


async def test_without_spool_limit_any_number_of_spools_fits(hass: HomeAssistant) -> None:
    hub = await _setup_hub(hass, subentries_data=[_spool_subentry(f"Spool {i}") for i in range(6)])
    await _start_spool_flow(hass, hub)  # still offers the form
    assert hass.states.get(SPOOL_COUNT_ENTITY).state == "6"


# --- hub (= filament box) flows ---------------------------------------------


async def test_hub_flow_creates_a_named_box_with_automatic_limits(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Filamentbox 1", CONF_HUMIDITY_SENSOR: "sensor.box_humidity"}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Filamentbox 1"
    assert result["data"][CONF_HUMIDITY_SENSOR] == "sensor.box_humidity"
    # Limit, delay and spool limit stay empty: automatic / unlimited.
    assert CONF_HUMIDITY_MAX not in result["data"]
    assert CONF_HUMIDITY_DELAY not in result["data"]
    assert CONF_SPOOL_LIMIT not in result["data"]


async def test_hub_flow_rejects_an_empty_name_and_allows_several_hubs(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "  "})
    assert result["type"] == "form"
    assert result["errors"] == {"name": "name_required"}

    for name in ("Filamentbox 1", "Filamentbox 2"):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": name})
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()

    assert sorted(entry.title for entry in hass.config_entries.async_entries(DOMAIN)) == [
        "Filamentbox 1",
        "Filamentbox 2",
    ]


def _box_subentries(entry: MockConfigEntry) -> list[ConfigSubentry]:
    return [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_BOX]


async def test_hub_flow_creates_a_box_subentry_named_like_the_hub(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Filamentbox 7"})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    hub = result["result"]
    boxes = _box_subentries(hub)
    assert [box.title for box in boxes] == ["Filamentbox 7"]


async def test_box_device_and_entities_belong_to_the_box_subentry(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.box_humidity", "30")
    hub = await _setup_hub(
        hass, subentries_data=[_spool_subentry()], **{CONF_HUMIDITY_SENSOR: "sensor.box_humidity"}
    )

    # A hub without its box subentry (e.g. from an earlier version) gets one, named like the hub.
    (box,) = _box_subentries(hub)
    assert box.title == HUB_TITLE

    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, hub.entry_id), hub.entry_id)
    assert device.config_entries_subentries == {hub.entry_id: {box.subentry_id}}

    registry = er.async_get(hass)
    for entity_id in (SPOOL_COUNT_ENTITY, HUMIDITY_ALERT):
        assert registry.async_get(entity_id).config_subentry_id == box.subentry_id

    # Spools stay in their own subentries and link to the box's device.
    spool = _subentry_by_title(hub, "Test Spool")
    assert registry.async_get(NUMBER_ENTITY).config_subentry_id == spool.subentry_id


async def test_legacy_box_device_and_entities_move_under_the_box_subentry(hass: HomeAssistant) -> None:
    """v0.10.0 registered the hub's device and entities directly on the entry."""
    hub = MockConfigEntry(domain=DOMAIN, title=HUB_TITLE, subentries_data=[_spool_subentry()])
    hub.add_to_hass(hass)

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    old_device = dev_reg.async_get_or_create(
        config_entry_id=hub.entry_id, identifiers={(DOMAIN, hub.entry_id)}, name=HUB_TITLE
    )
    ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{hub.entry_id}_spool_count", config_entry=hub, device_id=old_device.id
    )
    assert dev_reg.async_get(old_device.id).config_entries_subentries == {hub.entry_id: {None}}

    assert await hass.config_entries.async_setup(hub.entry_id)
    await hass.async_block_till_done()

    (box,) = _box_subentries(hub)
    device = dev_reg.async_get(old_device.id)  # same device, moved
    assert device.config_entries_subentries == {hub.entry_id: {box.subentry_id}}
    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{hub.entry_id}_spool_count")
    assert ent_reg.async_get(entity_id).config_subentry_id == box.subentry_id


async def test_box_subentry_follows_hub_renames(hass: HomeAssistant) -> None:
    hub = await _setup_hub(hass)

    # Via "Neu konfigurieren"...
    result = await hub.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Renamed Box"})
    assert result["type"] == "abort"
    await hass.async_block_till_done()
    assert [box.title for box in _box_subentries(hub)] == ["Renamed Box"]

    # ...and via the generic rename dialog.
    hass.config_entries.async_update_entry(hub, title="Renamed Again")
    await hass.async_block_till_done()
    assert [box.title for box in _box_subentries(hub)] == ["Renamed Again"]
    assert hub.state.value == "loaded"


async def test_removed_box_subentry_is_recreated(hass: HomeAssistant) -> None:
    hub = await _setup_hub(hass)
    (box,) = _box_subentries(hub)

    hass.config_entries.async_remove_subentry(hub, box.subentry_id)
    await hass.async_block_till_done()

    (new_box,) = _box_subentries(hub)
    assert new_box.subentry_id != box.subentry_id
    assert hass.states.get(SPOOL_COUNT_ENTITY) is not None


async def test_hub_only_supports_spool_subentries(hass: HomeAssistant) -> None:
    from custom_components.ha_filament_manager.config_flow import FilamentManagerConfigFlow

    hub = await _setup_hub(hass)
    assert list(FilamentManagerConfigFlow.async_get_supported_subentry_types(hub)) == [SUBENTRY_TYPE_SPOOL]


async def test_hub_reconfigure_updates_settings_and_can_reset_limits(hass: HomeAssistant) -> None:
    hub = await _setup_hub(
        hass, **{CONF_HUMIDITY_MAX: 45, CONF_HUMIDITY_DELAY: 5, CONF_SPOOL_LIMIT: 4}
    )

    result = await hub.start_reconfigure_flow(hass)
    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    # Submitting without the optional fields clears them again.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Renamed Box"})
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()

    assert hub.title == "Renamed Box"
    for key in (CONF_HUMIDITY_MAX, CONF_HUMIDITY_DELAY, CONF_SPOOL_LIMIT):
        assert key not in hub.data


# --- hub device and entities -------------------------------------------------


async def test_hub_device_exists_without_a_humidity_sensor_and_links_its_spools(hass: HomeAssistant) -> None:
    hub = await _setup_entry(hass)

    state = hass.states.get(SPOOL_COUNT_ENTITY)
    assert state is not None
    assert state.state == "1"
    assert state.attributes["spool_limit"] is None

    device_registry = dr.async_get(hass)
    box_device = device_registry.async_get_device_by_identifier((DOMAIN, hub.entry_id), hub.entry_id)
    assert box_device is not None
    assert box_device.name == HUB_TITLE

    spool = _subentry_by_title(hub, "Test Spool")
    spool_device = device_registry.async_get_device_by_identifier((DOMAIN, spool.subentry_id), hub.entry_id)
    assert spool_device is not None
    assert spool_device.via_device_id == box_device.id


async def test_humidity_alert_tracks_source_sensor(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.dry_box_humidity", "30")
    await hass.async_block_till_done()

    await _setup_hub(
        hass,
        subentries_data=[_spool_subentry()],
        **{CONF_HUMIDITY_SENSOR: "sensor.dry_box_humidity", CONF_HUMIDITY_MAX: 40, CONF_HUMIDITY_DELAY: 0},
    )

    state = hass.states.get(HUMIDITY_ALERT)
    assert state is not None
    assert state.state == "off"

    hass.states.async_set("sensor.dry_box_humidity", "55")
    await hass.async_block_till_done()

    state = hass.states.get(HUMIDITY_ALERT)
    assert state.state == "on"
    assert state.attributes["current_humidity"] == 55.0


async def test_humidity_alert_delay_ignores_short_spikes(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.dry_box_humidity", "30")
    await hass.async_block_till_done()

    await _setup_hub(
        hass,
        subentries_data=[_spool_subentry()],
        **{CONF_HUMIDITY_SENSOR: "sensor.dry_box_humidity", CONF_HUMIDITY_MAX: 40, CONF_HUMIDITY_DELAY: 30},
    )
    assert hass.states.get(HUMIDITY_ALERT).state == "off"

    # Too humid, but not for long enough yet.
    hass.states.async_set("sensor.dry_box_humidity", "55")
    await hass.async_block_till_done()
    assert hass.states.get(HUMIDITY_ALERT).state == "off"
    assert hass.states.get(HUMIDITY_ALERT).attributes["over_threshold"] is True

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=29))
    await hass.async_block_till_done()
    assert hass.states.get(HUMIDITY_ALERT).state == "off"

    # A dip below the threshold restarts the grace period.
    hass.states.async_set("sensor.dry_box_humidity", "30")
    await hass.async_block_till_done()
    hass.states.async_set("sensor.dry_box_humidity", "55")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=29))
    await hass.async_block_till_done()
    assert hass.states.get(HUMIDITY_ALERT).state == "off"


async def test_humidity_alert_delay_fires_when_sustained(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.dry_box_humidity", "30")
    await hass.async_block_till_done()

    await _setup_hub(
        hass,
        subentries_data=[_spool_subentry()],
        **{CONF_HUMIDITY_SENSOR: "sensor.dry_box_humidity", CONF_HUMIDITY_MAX: 40, CONF_HUMIDITY_DELAY: 30},
    )

    hass.states.async_set("sensor.dry_box_humidity", "55")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await hass.async_block_till_done()
    assert hass.states.get(HUMIDITY_ALERT).state == "on"

    # Staying humid keeps it on; dropping below clears it immediately.
    hass.states.async_set("sensor.dry_box_humidity", "60")
    await hass.async_block_till_done()
    assert hass.states.get(HUMIDITY_ALERT).state == "on"
    hass.states.async_set("sensor.dry_box_humidity", "30")
    await hass.async_block_till_done()
    assert hass.states.get(HUMIDITY_ALERT).state == "off"


async def test_hub_limits_follow_most_sensitive_material(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.box_humidity", "30")
    hub = await _setup_hub(hass, **{CONF_HUMIDITY_SENSOR: "sensor.box_humidity"})

    # Empty box: generic defaults.
    attributes = hass.states.get(HUMIDITY_ALERT).attributes
    assert attributes["threshold"] == DEFAULT_HUMIDITY_MAX
    assert attributes["delay_minutes"] == DEFAULT_HUMIDITY_DELAY

    # Nylon (20 %, 10 min) dominates PLA (50 %, 60 min) in the same box.
    _add_spool_subentry(hass, hub, "PLA Spool", **{CONF_MATERIAL: "PLA"})
    _add_spool_subentry(hass, hub, "Nylon Spool", **{CONF_MATERIAL: "Nylon"})
    await hass.async_block_till_done()
    attributes = hass.states.get(HUMIDITY_ALERT).attributes
    assert attributes["threshold"] == 20
    assert attributes["delay_minutes"] == 10


async def test_hub_explicit_limits_override_automatic(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.box_humidity", "30")
    await _setup_hub(
        hass,
        subentries_data=[_spool_subentry("Nylon Spool", **{CONF_MATERIAL: "Nylon"})],
        **{CONF_HUMIDITY_SENSOR: "sensor.box_humidity", CONF_HUMIDITY_MAX: 45, CONF_HUMIDITY_DELAY: 5},
    )

    attributes = hass.states.get(HUMIDITY_ALERT).attributes
    assert attributes["threshold"] == 45
    assert attributes["delay_minutes"] == 5


async def test_legacy_spool_humidity_entity_is_removed(hass: HomeAssistant) -> None:
    """Spools no longer monitor humidity on their own - only the hub does."""
    hass.states.async_set("sensor.old_humidity", "30")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=HUB_TITLE,
        subentries_data=[
            ConfigSubentryData(
                data=_spool_data(**{CONF_HUMIDITY_SENSOR: "sensor.old_humidity"}),
                subentry_id="spool1",
                subentry_type=SUBENTRY_TYPE_SPOOL,
                title="Test Spool",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "binary_sensor", DOMAIN, "spool1_humidity_alert", config_entry=entry, suggested_object_id="old_alert"
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(stale.entity_id) is None


# --- low stock and notifications --------------------------------------------


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


async def test_hub_humidity_alert_notifies_and_dismisses(hass: HomeAssistant) -> None:
    sent_messages = []

    async def _fake_send_message(call):
        sent_messages.append(dict(call.data))

    hass.services.async_register("notify", "send_message", _fake_send_message)

    notification_events = []
    async_dispatcher_connect(
        hass,
        pn.SIGNAL_PERSISTENT_NOTIFICATIONS_UPDATED,
        lambda update_type, notifications: notification_events.append((update_type, notifications)),
    )

    hass.states.async_set("sensor.dry_box_humidity", "30")
    await hass.async_block_till_done()

    await _setup_hub(
        hass,
        subentries_data=[_spool_subentry()],
        **{
            CONF_HUMIDITY_SENSOR: "sensor.dry_box_humidity",
            CONF_HUMIDITY_MAX: 40,
            CONF_HUMIDITY_DELAY: 0,
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


# --- card ---------------------------------------------------------------------


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


async def test_hubs_are_independent(hass: HomeAssistant) -> None:
    hub_a = await _setup_hub(hass, subentries_data=[_spool_subentry()])
    hub_b = await _setup_hub(hass, title="Other Box", subentries_data=[_spool_subentry("Other Spool")])

    assert hub_a.state.value == "loaded"
    assert hub_b.state.value == "loaded"
    assert hass.states.get(SPOOL_COUNT_ENTITY).state == "1"
    assert hass.states.get("sensor.other_box_spools").state == "1"
    assert hass.states.get("number.other_spool_remaining_weight") is not None
