# OSControll — Home Assistant

Кастомна інтеграція `custom_components/oscontroll/` та готовий Lovelace-дашборд:
агенти, телеметрія, метрики AMD GPU та керування (Wake / Power off / Reboot,
контейнери) — все на дашборді Home Assistant.

## 1. Встановлення інтеграції

**Варіант А — через HACS:**

1. HACS → **⋮ → Кастомні репозиторії** → додайте
   `https://github.com/arhcy/TinyOSControll` (категорія: **Integration**).
2. Відкрийте репозиторій **OSControll** і натисніть **Download**
   (оберіть реліз `v1.0.0`, якщо його пропонують).
3. Перезавантажте Home Assistant.

**Варіант Б — вручну:**

1. Скопіюйте папку `custom_components/oscontroll` у каталог конфігурації
   Home Assistant.
2. Перезавантажте Home Assistant.

## 2. Налаштування

**Налаштування → Пристрої та сервіси → Додати інтеграцію → OSControll**:

- URL: `https://<main-host>:8443`
- API-токен: `API_TOKEN` з `.env` main
- Якщо main використовує self-signed сертифікат (за замовчуванням),
  вимкніть "Перевіряти SSL-сертифікат".

Інтеграція опитує REST API main кожні 10 секунд; нові агенти та GPU
з'являються автоматично, без перезавантаження.

## 3. Сутності

| Елемент | Entity ID |
|---|---|
| Кількість агентів у мережі | `sensor.oscontroll_online_agents` |
| Агент у мережі | `binary_sensor.<agent>_online` |
| Температура CPU | `sensor.<agent>_cpu_temperature` |
| RAM / Swap | `sensor.<agent>_ram_usage`, `sensor.<agent>_ram_used`, `sensor.<agent>_swap_usage`, `sensor.<agent>_swap_used` |
| GPU (кожен) | `sensor.<agent>_gpu_<n>_power` / `_temperature` / `_memory_temperature` / `_gfx_clock` / `_gfx_utilization` / `_memory_utilization` / `_vram_used` / `_vram_total` |
| Wake / Power off / Reboot | `button.<agent>_wake` / `_power_off` / `_reboot` |
| Контейнер запущений | `binary_sensor.<agent>_<container>_running` |
| Керування контейнером | `button.<agent>_<container>_start` / `_stop` / `_restart` |

## 4. Готовий дашборд

`deploy/homeassistant/oscontroll-dashboard.yaml` — Lovelace-дашборд
(YAML-режим), що віддзеркалює веб-панель: одна картка на агента зі статусом
(online / offline), телеметрією (CPU/RAM/SWAP), метриками GPU, кнопками
**Wake / Power off / Reboot** та керуванням контейнерами (стан +
start / stop / restart). Коли агент offline — картка звужується до статусу
та кнопки Wake (аналогічно поведінці веб-версії). Використовуються лише
вбудовані картки, HACS не потрібен.

Вимога: свіжа версія Home Assistant (2024.10+, потрібні розділи в картці
`entities`).

### Встановлення

**Варіант 1 — через інтерфейс (найпростіший):**

1. **Налаштування → Дашборди → ⋮ (пра вгорі) → Додати дашборд**.
2. Назва: `OSControll`, іконка: `mdi:server`.
3. Режим: **YAML**.
4. Вставте весь вміст `oscontroll-dashboard.yaml`.
5. Збережіть.

**Варіант 2 — configuration.yaml:**

1. Скопіюйте `oscontroll-dashboard.yaml` у `<config>/dashboards/oscontroll.yaml`.
2. Додайте в `configuration.yaml`:

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

3. Перезавантажте Home Assistant.

### Адаптація під вашу конфігурацію

Дашборд згенеровано під типові значення з `.env.example`: агенти `alpha` і
`beta`, контейнери `nginx` і `postgres`, AMD GPU на `alpha`.

- **Назви агентів** — замінюйте `alpha` / `beta` в усіх entity ID та заголовках.
- **MAC / IP** — у заголовках `markdown` (рядки `MAC ... · IP ...`); беріть з
  `AGENT_<i>_MAC` / `AGENT_<i>_IP` у `deploy/main/.env`.
- **Контейнери** — розділи `nginx` / `postgres` мають відповідати `CONTAINERS`
  у `deploy/agent/.env` кожного агента; додавайте/видаляйте розділи за потреби
  (ID: `binary_sensor.<agent>_<container>_running`,
  `button.<agent>_<container>_start|stop|restart`).
- **GPU** — розділ `GPU 0` потрібен лише агентам з AMD GPU; для другого GPU
  додайте розділ `GPU 1` з ID `..._gpu_1_...`.
- **Entity ID** — інтеграція генерує ID з англійських назв сутностей
  (наприклад `sensor.alpha_ram_usage`). Якщо Home Assistant додав суфікс
  (наприклад `sensor.alpha_ram_usage_2`), візьміть фактичний ID у
  **Налаштування → Пристрої та сервіси → OSControll** і замініть у YAML.
