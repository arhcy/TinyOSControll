"""Data coordinator for OSControll."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import CannotConnect, InvalidAuth, OscontrollApi, OscontrollError
from .const import SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

# Fixed `amd-smi monitor` table header, must match main/web/app.js.
EXPECTED_HEADER = [
    "GPU", "XCP", "POWER", "GPU_T", "MEM_T", "GFX_CLK",
    "GFX%", "MEM%", "ENC%", "DEC%", "VRAM_USAGE",
]


def _num(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_amd_smi(text: Any) -> list[dict] | None:
    """Parse the fixed `amd-smi monitor` table into per-GPU dicts.

    Python port of parseAmdSmi() from main/web/app.js. Returns None when the
    layout is not recognized.
    """
    if not isinstance(text, str):
        return None
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    if lines[0].split() != EXPECTED_HEADER:
        return None
    gpus: list[dict] = []
    for line in lines[1:]:
        t = line.split()
        if (
            len(t) < 14
            or t[3] != "W" or t[5] != "°C" or t[7] != "°C"
            or t[9] != "MHz" or t[11] != "%" or t[13] != "%"
        ):
            return None
        if t[14] == "N/A":
            if len(t) != 20 or t[16] != "%" or t[19] != "GB":
                return None
            enc = None
            dec = _num(t[15])
            vram_used = _num(t[17])
            vram_total = _num(t[18])
        else:
            if len(t) != 21 or t[15] != "%" or t[17] != "%" or t[20] != "GB":
                return None
            enc = _num(t[14])
            dec = _num(t[16])
            vram_used = _num(t[18])
            vram_total = _num(t[19])
        gpus.append(
            {
                "gpu": int(t[0]),
                "xcp": int(t[1]),
                "power_w": _num(t[2]),
                "gpu_temp_c": _num(t[4]),
                "mem_temp_c": _num(t[6]),
                "gfx_clk_mhz": _num(t[8]),
                "gfx_pct": _num(t[10]),
                "mem_pct": _num(t[12]),
                "enc_pct": enc,
                "dec_pct": dec,
                "vram_used_gb": vram_used,
                "vram_total_gb": vram_total,
            }
        )
    return gpus or None


class OscontrollCoordinator(DataUpdateCoordinator[dict[str, dict]]):
    """Polls /api/agents (telemetry included) plus per-agent containers."""

    config_entry = None

    def __init__(self, hass, api: OscontrollApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="oscontroll",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, dict]:
        try:
            agents = await self.api.get_agents()
        except (CannotConnect, InvalidAuth) as exc:
            raise UpdateFailed(f"Cannot reach OSControll main: {exc}") from exc
        data: dict[str, dict] = {}
        for agent in agents:
            item = dict(agent)
            item["gpus"] = parse_amd_smi(
                (agent.get("telemetry") or {}).get("amd_smi")
            )
            try:
                item["containers"] = await self.api.get_containers(agent["name"])
            except OscontrollError as exc:
                # Offline agent or agent error: keep the entry, no containers.
                _LOGGER.debug("containers for %s: %s", agent["name"], exc)
                item["containers"] = None
            data[agent["name"]] = item
        return data
