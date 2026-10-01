"""Constants for the Filament Manager integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "ha_filament_manager"

CONF_NAME: Final = "name"
CONF_MATERIAL: Final = "material"
CONF_COLOR: Final = "color"
CONF_MANUFACTURER: Final = "manufacturer"
CONF_DIAMETER: Final = "diameter"
CONF_TOTAL_WEIGHT: Final = "total_weight"
CONF_INITIAL_REMAINING_WEIGHT: Final = "initial_remaining_weight"
CONF_HUMIDITY_SENSOR: Final = "humidity_sensor"
CONF_HUMIDITY_MAX: Final = "humidity_max"
CONF_HUMIDITY_DELAY: Final = "humidity_delay"
CONF_LOW_STOCK_THRESHOLD: Final = "low_stock_threshold"
CONF_NOTIFY_TARGETS: Final = "notify_targets"
CONF_PERSISTENT_NOTIFICATION: Final = "persistent_notification"
# Optional upper limit on the number of spools in a hub (empty = unlimited).
CONF_SPOOL_LIMIT: Final = "spool_limit"

# A config entry is a hub, and a hub *is* one filament box (or shelf): its
# data holds the box's humidity sensor, limits and notification settings.
# Every spool is a config subentry of a hub.
SUBENTRY_TYPE_SPOOL: Final = "spool"

DEFAULT_TOTAL_WEIGHT: Final = 1000
DEFAULT_HUMIDITY_MAX: Final = 40
DEFAULT_HUMIDITY_DELAY: Final = 30
DEFAULT_MATERIAL: Final = "PETG"
DEFAULT_DIAMETER: Final = "1.75"

MATERIAL_OPTIONS: Final[list[str]] = [
    "PLA",
    "PETG",
    "ABS",
    "ASA",
    "TPU",
    "PC",
    "Nylon",
    "PVA",
    "HIPS",
    "Sonstiges",
]

COLOR_OPTIONS: Final[list[str]] = [
    "Schwarz",
    "Weiß",
    "Grau",
    "Silber",
    "Rot",
    "Blau",
    "Himmelblau",
    "Grün",
    "Meeresgrün",
    "Gelb",
    "Orange",
    "Lila",
    "Pink",
    "Braun",
    "Holzfarbe",
    "Beige",
    "Transparent",
    "Gold",
    "Sonstige",
]

MANUFACTURER_OPTIONS: Final[list[str]] = [
    "Prusament",
    "Bambu Lab",
    "eSUN",
    "SUNLU",
    "Polymaker",
    "Overture",
    "Devil Design",
    "Extrudr",
    "Fillamentum",
    "Formfutura",
    "ColorFabb",
    "3DJake",
    "Das Filament",
    "Elegoo",
    "Sonstiges",
]

DIAMETER_OPTIONS: Final[list[dict[str, str]]] = [
    {"value": "1.75", "label": "1.75 mm"},
    {"value": "2.85", "label": "2.85 mm"},
]

# Total-weight suggestions, most specific match wins:
#   1. MANUFACTURER_MATERIAL_WEIGHTS[manufacturer][material]
#   2. MATERIAL_DEFAULT_WEIGHTS[material]
#   3. DEFAULT_TOTAL_WEIGHT
#
# MANUFACTURER_MATERIAL_WEIGHTS starts empty on purpose: real per-manufacturer
# spool weights vary by product line and change over time, so it should only
# ever contain values someone has actually verified (e.g. from their own
# spools) - add entries as you confirm them, in grams:
#   "Bambu Lab": {"PLA": 1000},
MANUFACTURER_MATERIAL_WEIGHTS: Final[dict[str, dict[str, int]]] = {}

# Material-only fallback for well-documented, brand-independent industry
# conventions: flexible (TPU) and water-soluble support material (PVA) are
# commonly sold in smaller spools than the standard 1000 g across most
# manufacturers, due to higher cost and printing difficulty. Not a guarantee
# for any specific product - MANUFACTURER_MATERIAL_WEIGHTS above always wins
# when a real value is known.
MATERIAL_DEFAULT_WEIGHTS: Final[dict[str, int]] = {
    "TPU": 500,
    "PVA": 500,
}


def suggested_total_weight(manufacturer: str | None, material: str | None) -> int:
    """Suggest a spool's total weight from its manufacturer and material."""
    manufacturer = (manufacturer or "").strip()
    material = (material or "").strip()
    if manufacturer and material:
        weight = MANUFACTURER_MATERIAL_WEIGHTS.get(manufacturer, {}).get(material)
        if weight is not None:
            return weight
    if material in MATERIAL_DEFAULT_WEIGHTS:
        return MATERIAL_DEFAULT_WEIGHTS[material]
    return DEFAULT_TOTAL_WEIGHT


# Suggested maximum relative humidity (%) per material, i.e. the value above
# which storing that filament becomes a problem. Rules of thumb from common
# manufacturer guidance: hygroscopic materials (Nylon, PVA) need to be kept
# far drier than PLA/ABS. Only a suggestion - always freely adjustable, and
# a specific manufacturer's datasheet takes precedence.
MATERIAL_HUMIDITY_MAX: Final[dict[str, int]] = {
    "PLA": 50,
    "ABS": 50,
    "ASA": 50,
    "HIPS": 50,
    "PETG": 40,
    "TPU": 30,
    "PC": 30,
    "Nylon": 20,
    "PVA": 20,
}


def suggested_humidity_max(material: str | None) -> int:
    """Suggest a maximum humidity threshold (%) for a filament material."""
    return MATERIAL_HUMIDITY_MAX.get((material or "").strip(), DEFAULT_HUMIDITY_MAX)


# Suggested grace period (minutes) the humidity has to stay above the limit
# before the alert fires, per material. Filament absorbs moisture over hours
# to days, so a short spike (opening the box, swapping a spool) is harmless;
# the more hygroscopic the material, the sooner it should be flagged.
MATERIAL_HUMIDITY_DELAY: Final[dict[str, int]] = {
    "PLA": 60,
    "ABS": 60,
    "ASA": 60,
    "HIPS": 60,
    "PETG": 30,
    "TPU": 20,
    "PC": 20,
    "Nylon": 10,
    "PVA": 10,
}


def suggested_humidity_delay(material: str | None) -> int:
    """Suggest how many minutes humidity must stay too high before alerting."""
    return MATERIAL_HUMIDITY_DELAY.get((material or "").strip(), DEFAULT_HUMIDITY_DELAY)


SERVICE_CONSUME_FILAMENT: Final = "consume_filament"
SERVICE_REFILL_SPOOL: Final = "refill_spool"

ATTR_AMOUNT: Final = "amount"

CARD_FILENAME: Final = "filament-manager-card.js"
CARD_URL_PATH: Final = f"/{DOMAIN}_files/{CARD_FILENAME}"
# Bump whenever the card's JS changes, to bust browser caching of the
# static file (independent of the integration's own manifest version).
CARD_VERSION: Final = "15"


def signal_spool_updated(subentry_id: str) -> str:
    """Return the dispatcher signal name used for a spool's live updates."""
    return f"{DOMAIN}_{subentry_id}_updated"
