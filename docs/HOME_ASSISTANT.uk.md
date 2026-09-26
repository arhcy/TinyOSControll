# OSControll — Home Assistant

Кастомна інтеграція `custom_components/oscontroll/`: агенти, телеметрія,
метрики AMD GPU та керування (Wake / Power off / Reboot, контейнери) —
все в Home Assistant.

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
