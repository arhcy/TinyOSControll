"""Diagnostics for the OSControll integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return diagnostics data for the config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    return {
        "config": {**entry.data, "token": "****"},
        "coordinator": data["coordinator"].data,
    }
