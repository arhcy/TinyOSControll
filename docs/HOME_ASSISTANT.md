# OSControll — Home Assistant

A custom integration (`custom_components/oscontroll/`) plus a ready-made
Lovelace dashboard: agents, telemetry, AMD GPU metrics and controls
(Wake / Power off / Reboot, containers) — all in a Home Assistant dashboard.

## 1. Installing the integration

1. Copy the `custom_components/oscontroll` folder into your Home Assistant
   config directory (or add this repository to HACS as a custom repo and
   install "OSControll").
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

## 4. Ready-made dashboard

`deploy/homeassistant/oscontroll-dashboard.yaml` — a Lovelace dashboard
(YAML mode) that mirrors the web UI: one card per agent with status
(online / offline), telemetry (CPU/RAM/SWAP), GPU metrics,
**Wake / Power off / Reboot** buttons and container controls (state +
start / stop / restart). When an agent is offline, its card collapses to
the status and the Wake button (same behavior as the web version). Only
built-in cards are used, no HACS required.

Requirement: a recent Home Assistant version (2024.10+, sections in the
`entities` card are required).

### Installation

**Option 1 — via the UI (easiest):**

1. **Settings → Dashboards → ⋮ (top right) → Add dashboard**.
2. Name: `OSControll`, icon: `mdi:server`.
3. Mode: **YAML**.
4. Paste the full content of `oscontroll-dashboard.yaml`.
5. Save.

**Option 2 — configuration.yaml:**

1. Copy `oscontroll-dashboard.yaml` to `<config>/dashboards/oscontroll.yaml`.
2. Add to `configuration.yaml`:

```yaml
lovelace:
  dashboards:
    oscontroll:
      mode: yaml
      title: OSControll
      icon: mdi:server
      show_in_sidebar: true
      filename: dashboards/oscontroll.yaml
```

3. Restart Home Assistant.

### Adapting to your setup

The dashboard is generated for the default `.env.example` values: agents
`alpha` and `beta`, containers `nginx` and `postgres`, AMD GPU on `alpha`.

- **Agent names** — replace `alpha` / `beta` in all entity IDs and headers.
- **MAC / IP** — in the `markdown` headers (the `MAC ... · IP ...` lines);
  take them from `AGENT_<i>_MAC` / `AGENT_<i>_IP` in `deploy/main/.env`.
- **Containers** — the `nginx` / `postgres` sections must match `CONTAINERS`
  in each agent's `deploy/agent/.env`; add/remove sections as needed
  (IDs: `binary_sensor.<agent>_<container>_running`,
  `button.<agent>_<container>_start|stop|restart`).
- **GPU** — the `GPU 0` section is only needed for agents with an AMD GPU;
  for a second GPU add a `GPU 1` section with `..._gpu_1_...` IDs.
- **Entity IDs** — the integration generates IDs from the English entity
  names (e.g. `sensor.alpha_ram_usage`). If Home Assistant appended a
  suffix (e.g. `sensor.alpha_ram_usage_2`), take the actual ID from
  **Settings → Devices & Services → OSControll** and replace it in the YAML.
