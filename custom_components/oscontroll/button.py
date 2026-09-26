"""Button platform for OSControll."""
from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import OscontrollError
from .const import CONTAINER_ACTIONS, DOMAIN
from .coordinator import OscontrollCoordinator
from .discovery import agent_device_info, created_set

_LOGGER = logging.getLogger(__name__)

WAKE = ButtonEntityDescription(key="wake")
POWER_OFF = ButtonEntityDescription(key="power_off")
REBOOT = ButtonEntityDescription(key="reboot")

CONTAINER_BUTTONS = {
    "start": ButtonEntityDescription(key="container_start"),
    "stop": ButtonEntityDescription(key="container_stop"),
    "restart": ButtonEntityDescription(key="container_restart"),
}


class AgentButton(CoordinatorEntity[OscontrollCoordinator], ButtonEntity):
    """Button that calls a main API action for one agent."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OscontrollCoordinator,
        description: ButtonEntityDescription,
        agent_name: str,
        device_info: dict,
        action_fn: Callable[[str], object],
        unique_id: str,
        translation_placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._agent_name = agent_name
        self._attr_device_info = device_info
        self._action_fn = action_fn
        self._attr_unique_id = unique_id
        self._attr_translation_key = description.key
        if translation_placeholders:
            self._attr_translation_placeholders = translation_placeholders

    async def async_press(self) -> None:
        try:
            await self._action_fn(self._agent_name)
        except OscontrollError as exc:
            _LOGGER.warning(
                "OSControll action failed for %s: %s", self._agent_name, exc
            )
        await self.coordinator.async_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up buttons."""
    coordinator: OscontrollCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    api = coordinator.api
    created = created_set(hass, entry, "button")

    def refresh() -> None:
        new = []
        for name, agent in coordinator.data.items():
            if name not in created:
                created.add(name)
                device_info = agent_device_info(agent)
                for description, action in (
                    (WAKE, "wake"),
                    (POWER_OFF, "poweroff"),
                    (REBOOT, "reboot"),
                ):
                    new.append(
                        AgentButton(
                            coordinator,
                            description,
                            name,
                            device_info,
                            partial(api.action, action=action),
                            unique_id=f"{DOMAIN}:{name}:{description.key}",
                        )
                    )
            for container in (agent.get("containers") or {}):
                for action_name in CONTAINER_ACTIONS:
                    ckey = f"{name}:container:{container}:{action_name}"
                    if ckey not in created:
                        created.add(ckey)
                        new.append(
                            AgentButton(
                                coordinator,
                                CONTAINER_BUTTONS[action_name],
                                name,
                                agent_device_info(agent),
                                partial(
                                    api.container_action,
                                    container=container,
                                    action=action_name,
                                ),
                                unique_id=(
                                    f"{DOMAIN}:{name}:container:{container}:{action_name}"
                                ),
                                translation_placeholders={"container": container},
                            )
                        )
        if new:
            async_add_entities(new)

    refresh()
    coordinator.async_add_listener(refresh)
