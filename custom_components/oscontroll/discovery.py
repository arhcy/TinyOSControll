"""Shared helpers for per-agent entity discovery."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN, HUB_ID


def hub_device_info() -> dict:
    """Device info for the main server (hub) device."""
    return {
        "identifiers": {(DOMAIN, HUB_ID)},
        "name": "OSControll",
        "model": "main",
    }


def agent_device_info(agent: dict) -> dict:
    """Device info for one agent."""
    return {
        "identifiers": {(DOMAIN, agent["name"])},
        "name": agent["name"],
        "model": "agent",
        "serial_number": agent.get("mac"),
        "via_device": (DOMAIN, HUB_ID),
    }


def created_set(hass: HomeAssistant, entry, platform: str) -> set:
    """Per-entry, per-platform set of already-created entity keys."""
    store = hass.data[DOMAIN][entry.entry_id]
    key = f"_created_{platform}"
    if key not in store:
        store[key] = set()
    return store[key]
