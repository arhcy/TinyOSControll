"""The OSControll integration."""
from __future__ import annotations

import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .api import CannotConnect, InvalidAuth, OscontrollApi
from .const import CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL, DOMAIN
from .coordinator import OscontrollCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OSControll from a config entry."""
    session = aiohttp.ClientSession()
    api = OscontrollApi(
        session,
        entry.data[CONF_URL],
        entry.data[CONF_TOKEN],
        entry.data[CONF_VERIFY_SSL],
    )
    coordinator = OscontrollCoordinator(hass, api)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "session": session,
        "coordinator": coordinator,
    }
    try:
        await coordinator.async_refresh()
    except (CannotConnect, InvalidAuth) as exc:
        await session.close()
        del hass.data[DOMAIN][entry.entry_id]
        raise ConfigEntryNotReady(
            f"Cannot connect to OSControll main: {exc}"
        ) from exc

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    session: aiohttp.ClientSession = hass.data[DOMAIN][entry.entry_id]["session"]
    await session.close()
    del hass.data[DOMAIN][entry.entry_id]
    return True
