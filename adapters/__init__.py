from __future__ import annotations

import json
from typing import Dict, Tuple

from booking_engine import BookingEngine, Library
from adapters.base import BaseLibraryAdapter
from adapters.libcal import LibCalAdapter
from adapters.mock import MockAdapter
from adapters.scraper import ScraperAdapter

_ADAPTER_MAP = {
    "libcal": LibCalAdapter,
    "scraper": ScraperAdapter,
    "mock": MockAdapter,
}


def load_libraries(
    engine: BookingEngine,
    config_path: str = "libraries.json",
) -> Dict[str, Library]:
    """Parse libraries.json, build adapters, register them with engine.

    Returns a {library_id: Library} dict for the UI to display.
    """
    with open(config_path) as fh:
        configs = json.load(fh)

    libraries: Dict[str, Library] = {}
    for cfg in configs:
        lib = Library(
            id=cfg["id"],
            name=cfg["name"],
            campus=cfg.get("campus", ""),
            building=cfg.get("building", ""),
            base_url=cfg.get("base_url", ""),
            adapter_type=cfg["adapter"],
            open_time=cfg.get("open_time", "08:00"),
            close_time=cfg.get("close_time", "22:00"),
            open_days=cfg.get("open_days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
            max_booking_days_ahead=cfg.get("max_booking_days_ahead", 7),
            max_booking_duration_hours=cfg.get("max_booking_duration_hours", 2),
            max_bookings_per_user_per_day=cfg.get("max_bookings_per_user_per_day", 1),
        )
        adapter_cls = _ADAPTER_MAP.get(cfg["adapter"])
        if adapter_cls is None:
            raise ValueError(f"Unknown adapter '{cfg['adapter']}' for library '{cfg['id']}'")
        engine.register_library(lib.id, adapter_cls(lib, cfg))
        libraries[lib.id] = lib

    return libraries


__all__ = [
    "BaseLibraryAdapter", "LibCalAdapter", "ScraperAdapter", "MockAdapter",
    "load_libraries",
]
