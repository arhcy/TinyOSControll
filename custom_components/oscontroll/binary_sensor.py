"""Binary sensor platform for OSControll."""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OscontrollCoordinator
from .discovery import agent_device_info, created_set

ONLINE = BinarySensorEntityDescription(
    key="online",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)

CONTAINER_RUNNING = BinarySensorEntityDescription(
    key="container_running",
    device_class=BinarySensorDeviceClass.RUNNING,
)


class AgentBinarySensor(
    CoordinatorEntity[OscontrollCoordinator], BinarySensorEntity
):
    """Binary sensor bound to one agent."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OscontrollCoordinator,
        description: BinarySensorEntityDescription,
        agent_name: str,
        device_info: dict,
        value_fn: Callable[[dict], bool | None],
        translation_placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._agent_name = agent_name
        self._attr_device_info = device_info
        self._value_fn = value_fn
        if translation_placeholders:
            self._attr_translation_placeholders = translation_placeholders

    @property
    def is_on(self) -> bool | None:
        agent = self.coordinator.data.get(self._agent_name)
        if agent is None:
            return None
        return self._value_fn(agent)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator: OscontrollCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    created = created_set(hass, entry, "binary_sensor")

    def refresh() -> None:
        new = []
        for name, agent in coordinator.data.items():
            if name not in created:
                created.add(name)
                device_info = agent_device_info(agent)
                new.append(
                    AgentBinarySensor(
                        coordinator,
                        ONLINE,
                        name,
                        device_info,
                        lambda a: bool(a.get("online")),
                    )
                )
            for container in (agent.get("containers") or {}):
                ckey = f"{name}:container:{container}"
                if ckey not in created:
                    created.add(ckey)
                    new.append(
                        AgentBinarySensor(
                            coordinator,
                            CONTAINER_RUNNING,
                            name,
                            agent_device_info(agent),
                            lambda a, c=container: (
                                (a.get("containers") or {}).get(c, {})
                                .get("state")
                                == "running"
                            ),
                            translation_placeholders={"container": container},
                        )
                    )
        if new:
            async_add_entities(new)

    refresh()
    coordinator.async_add_listener(refresh)
