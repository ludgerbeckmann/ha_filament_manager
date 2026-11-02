"""Small helpers for the choices offered when a spool is created."""
from __future__ import annotations

from typing import Any

from .const import CONF_COLOR, CONF_MANUFACTURER, CONF_MATERIAL

# "Other"-style catch-all entries always go last, whatever the alphabet says.
CATCH_ALL_OPTIONS = {"Sonstiges", "Sonstige"}


def sorted_options(options: list[str]) -> list[str]:
    """Sort dropdown options alphabetically, with the catch-all entry last."""
    return sorted(options, key=lambda option: (option in CATCH_ALL_OPTIONS, option.casefold()))


def suggest_name(data: dict[str, Any]) -> str:
    """Suggest a spool name built from its manufacturer, material and color."""
    parts = [
        data.get(CONF_MANUFACTURER, "").strip(),
        data.get(CONF_MATERIAL, "").strip(),
        data.get(CONF_COLOR, "").strip(),
    ]
    return " ".join(part for part in parts if part) or "Filamentspule"
