"""What a running Filament Manager entry holds."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .ams import AmsTracker
from .cloud_sync import CloudSync
from .const import DOMAIN
from .printing import PrintNotifier
from .store import FilamentManager


@dataclass
class FilamentRuntime:
    """The inventory, its AMS and cloud followers and the platforms' entity syncers."""

    manager: FilamentManager
    ams: AmsTracker
    cloud: CloudSync
    printing: PrintNotifier
    # Called (without arguments) whenever boxes or spools were added, changed or removed.
    syncers: list[Callable[[], None]] = field(default_factory=list)


def get_runtime(hass) -> FilamentRuntime | None:
    """The running inventory (there is one Filament Manager entry), if it is loaded."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        if isinstance(getattr(entry, "runtime_data", None), FilamentRuntime):
            return entry.runtime_data
    return None
