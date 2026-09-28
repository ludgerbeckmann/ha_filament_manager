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

SERVICE_CONSUME_FILAMENT: Final = "consume_filament"
SERVICE_REFILL_SPOOL: Final = "refill_spool"

ATTR_AMOUNT: Final = "amount"

CARD_FILENAME: Final = "filament-manager-card.js"
CARD_URL_PATH: Final = f"/{DOMAIN}_files/{CARD_FILENAME}"
# Bump whenever the card's JS changes, to bust browser caching of the
# static file (independent of the integration's own manifest version).
CARD_VERSION: Final = "1"


def signal_spool_updated(entry_id: str) -> str:
    """Return the dispatcher signal name used for a spool's live updates."""
    return f"{DOMAIN}_{entry_id}_updated"
