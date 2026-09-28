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
CONF_LOW_STOCK_THRESHOLD: Final = "low_stock_threshold"
CONF_NOTIFY_TARGETS: Final = "notify_targets"
CONF_PERSISTENT_NOTIFICATION: Final = "persistent_notification"

DEFAULT_TOTAL_WEIGHT: Final = 1000
DEFAULT_HUMIDITY_MAX: Final = 40
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
    "Grün",
    "Gelb",
    "Orange",
    "Lila",
    "Pink",
    "Braun",
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


SERVICE_CONSUME_FILAMENT: Final = "consume_filament"
SERVICE_REFILL_SPOOL: Final = "refill_spool"

ATTR_AMOUNT: Final = "amount"

CARD_FILENAME: Final = "filament-manager-card.js"
CARD_URL_PATH: Final = f"/{DOMAIN}_files/{CARD_FILENAME}"
# Bump whenever the card's JS changes, to bust browser caching of the
# static file (independent of the integration's own manifest version).
CARD_VERSION: Final = "4"


def signal_spool_updated(entry_id: str) -> str:
    """Return the dispatcher signal name used for a spool's live updates."""
    return f"{DOMAIN}_{entry_id}_updated"
