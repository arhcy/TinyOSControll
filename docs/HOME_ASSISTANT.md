# OSControll — Home Assistant

A custom integration (`custom_components/oscontroll/`): agents, telemetry,
AMD GPU metrics and controls (Wake / Power off / Reboot, containers) —
all in Home Assistant.

## 1. Installing the integration

**Option A — via HACS:**

1. HACS → **⋮ → Custom repositories** → add
   `https://github.com/arhcy/TinyOSControll` (category: **Integration**).
2. Open the **OSControll** repository and press **Download** (pick the
   `v1.0.0` release if it is offered).
3. Restart Home Assistant.

**Option B — manual:**

1. Copy the `custom_components/oscontroll` folder into your Home Assistant
   config directory.
2. Restart Home Assistant.

## 2. Configuration

**Settings → Devices & Services → Add Integration → OSControll**:

- URL: `https://<main-host>:8443`
- API token: the `API_TOKEN` from main's `.env`
- If main uses a self-signed certificate (the default), disable
  "Verify SSL certificate".

The integration polls the main REST API every 10 seconds; new agents and
GPUs are picked up automatically without a restart.

## 3. Entities

| Element | Entity ID |
|---|---|
| Agents online | `sensor.oscontroll_online_agents` |
| Agent online | `binary_sensor.<agent>_online` |
| CPU temperature | `sensor.<agent>_cpu_temperature` |
| RAM / Swap | `sensor.<agent>_ram_usage`, `sensor.<agent>_ram_used`, `sensor.<agent>_swap_usage`, `sensor.<agent>_swap_used` |
| GPU (each) | `sensor.<agent>_gpu_<n>_power` / `_temperature` / `_memory_temperature` / `_gfx_clock` / `_gfx_utilization` / `_memory_utilization` / `_vram_used` / `_vram_total` |
| Wake / Power off / Reboot | `button.<agent>_wake` / `_power_off` / `_reboot` |
| Container running | `binary_sensor.<agent>_<container>_running` |
 | Container controls | `button.<agent>_<container>_start` / `_stop` / `_restart` |
