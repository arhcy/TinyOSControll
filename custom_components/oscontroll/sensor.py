"""Sensor platform for OSControll."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OscontrollCoordinator
from .discovery import agent_device_info, created_set, hub_device_info

AGENTS_ONLINE = SensorEntityDescription(
    key="agents_online",
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement="agents",
)


class OscontrollSensor(CoordinatorEntity[OscontrollCoordinator], SensorEntity):
    """Base sensor backed by the coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OscontrollCoordinator,
        description: SensorEntityDescription,
        device_info: dict,
        value_fn: Callable[[dict], Any],
        translation_placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_device_info = device_info
        self._value_fn = value_fn
        if translation_placeholders:
            self._attr_translation_placeholders = translation_placeholders

    @property
    def native_value(self) -> Any:
        return self._value_fn(self.coordinator.data)


class AgentSensor(OscontrollSensor):
    """Sensor bound to one agent."""

    def __init__(self, *args, agent_name: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._agent_name = agent_name

    @property
    def native_value(self) -> Any:
        agent = self.coordinator.data.get(self._agent_name)
        if agent is None:
            return None
        return self._value_fn(agent)


class GpuSensor(AgentSensor):
    """Sensor bound to one GPU of one agent."""

    def __init__(self, *args, gpu_index: int, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._gpu_index = gpu_index

    @property
    def native_value(self) -> Any:
        agent = self.coordinator.data.get(self._agent_name)
        if agent is None:
            return None
        for gpu in agent.get("gpus") or []:
            if gpu["gpu"] == self._gpu_index:
                return self._value_fn(gpu)
        return None


AGENT_SENSORS: tuple[SensorEntityDescription, Callable[[dict], Any]] = (
    (
        SensorEntityDescription(
            key="cpu_temp",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="°C",
        ),
        lambda a: (a.get("telemetry") or {}).get("cpu_temp_c"),
    ),
    (
        SensorEntityDescription(
            key="ram_percent",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="%",
        ),
        lambda a: (a.get("telemetry") or {}).get("ram", {}).get("percent"),
    ),
    (
        SensorEntityDescription(
            key="ram_used",
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="MB",
        ),
        lambda a: (a.get("telemetry") or {}).get("ram", {}).get("used_mb"),
    ),
    (
        SensorEntityDescription(
            key="swap_percent",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="%",
        ),
        lambda a: (a.get("telemetry") or {}).get("swap", {}).get("percent"),
    ),
    (
        SensorEntityDescription(
            key="swap_used",
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="MB",
        ),
        lambda a: (a.get("telemetry") or {}).get("swap", {}).get("used_mb"),
    ),
)

GPU_SENSORS: tuple[SensorEntityDescription, Callable[[dict], Any]] = (
    (
        SensorEntityDescription(
            key="gpu_power",
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="W",
        ),
        lambda g: g.get("power_w"),
    ),
    (
        SensorEntityDescription(
            key="gpu_temp",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="°C",
        ),
        lambda g: g.get("gpu_temp_c"),
    ),
    (
        SensorEntityDescription(
            key="gpu_mem_temp",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="°C",
        ),
        lambda g: g.get("mem_temp_c"),
    ),
    (
        SensorEntityDescription(
            key="gpu_gfx_clock",
            device_class=SensorDeviceClass.FREQUENCY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="MHz",
        ),
        lambda g: g.get("gfx_clk_mhz"),
    ),
    (
        SensorEntityDescription(
            key="gpu_gfx_utilization",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="%",
        ),
        lambda g: g.get("gfx_pct"),
    ),
    (
        SensorEntityDescription(
            key="gpu_mem_utilization",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="%",
        ),
        lambda g: g.get("mem_pct"),
    ),
    (
        SensorEntityDescription(
            key="gpu_vram_used",
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement="GB",
        ),
        lambda g: g.get("vram_used_gb"),
    ),
    (
        SensorEntityDescription(
            key="gpu_vram_total",
            device_class=SensorDeviceClass.DATA_SIZE,
            native_unit_of_measurement="GB",
        ),
        lambda g: g.get("vram_total_gb"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator: OscontrollCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    created = created_set(hass, entry, "sensor")

    async_add_entities(
        [
            OscontrollSensor(
                coordinator,
                AGENTS_ONLINE,
                hub_device_info(),
                lambda data: sum(1 for a in data.values() if a.get("online")),
            )
        ]
    )

    def refresh() -> None:
        new = []
        for name, agent in coordinator.data.items():
            if name not in created:
                created.add(name)
                device_info = agent_device_info(agent)
                for description, value_fn in AGENT_SENSORS:
                    new.append(
                        AgentSensor(
                            coordinator,
                            description,
                            device_info,
                            value_fn,
                            agent_name=name,
                        )
                    )
            for gpu in agent.get("gpus") or []:
                gkey = f"{name}:gpu{gpu['gpu']}"
                if gkey not in created:
                    created.add(gkey)
                    for description, value_fn in GPU_SENSORS:
                        new.append(
                            GpuSensor(
                                coordinator,
                                description,
                                agent_device_info(agent),
                                value_fn,
                                agent_name=name,
                                gpu_index=gpu["gpu"],
                                translation_placeholders={"index": str(gpu["gpu"])},
                            )
                        )
        if new:
            async_add_entities(new)

    refresh()
    coordinator.async_add_listener(refresh)
