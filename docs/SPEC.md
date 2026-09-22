# TinyOSControll — специфікація

Мережевий інструмент керування серверами: веб-панель на центральній машині
(**main**) керує кількома віддаленими серверами (**agent**) — Wake-on-LAN,
вимкнення, ребут, керування заздалегідь визначеними Docker-контейнерами та
жива телеметрія (CPU/RAM/SWAP/GPU).

Весь код — **Python** (демони, веб) та **bash** (скрипти розгортання,
диспетчер системних команд). Без SSH, без виконання довільних команд.

## 1. Архітектура

Два типи інстансів (назви використовуються в коді та документації):

| Інстанс | Що це | Де працює |
|---|---|---|
| **main** | контейнер: веб-інтерфейс (HTTPS) + система, що спілкується з агентами (mTLS-WS-сервер) + WoL | центральний сервер |
| **agent** | контейнер: один демон, що обробляє всі команди + bash-диспетчер системних команд | кожен керований сервер (агентів може бути кілька) |

Ключові рішення:

- **Агент ініціює вихідне з'єднання** з main. Agent не відкриває жодних
  вхідних портів — його фаєрвол може бути закритим повністю.
- **Одна двостороння mTLS-WebSocket-сесія** несе і телеметрію (agent→main),
  і запити керування (main→agent).
- **WoL надсилає main** (магічний пакет має йти по LAN; вимкнена машина
  виконувати команди не може). Main працює в `network_mode: host`, щоб
  broadcast дійшов до мережі.
- **Agent — один демон** (`agent.py`) + **один bash-скрипт** (`hostcmd.sh`),
  який викликає лише жорстко визначений набір системних команд.
- **Все встановлюється через docker compose**: користувач копіює compose-файл,
  редагує `.env`, запускає `docker compose up -d`.
- **Мінімальні залежності хостів**: main — лише Docker; agent — лише Docker
  (+ `amd-smi` для GPU-телеметрії, якщо є GPU).

## 2. Протокол

- JSON-повідомлення поверх **WebSocket**, **mTLS** (спільний self-signed
  сертифікат), TLS ≥ 1.2.
- **Без SSH, без виконання довільних команд** — лише фіксований набір дій.

Повідомлення:

```json
{"type":"hello","agent":"alpha","token":"…"}
{"type":"hello_ok"}
{"type":"hello_err","reason":"unknown agent"}
{"type":"request","id":"…","action":"poweroff"}
{"type":"response","id":"…","ok":true,"payload":{...}}
{"type":"telemetry","agent":"alpha","ts":"…","payload":{...}}
{"type":"ping"} / {"type":"pong"}
{"type":"bye"}
```

Дії керування (main→agent): `health`, `poweroff`, `reboot`,
`containers.list`, `containers.action`.

## 3. Функції

1. **Wake-on-LAN** — магічний пакет (6×FF + 16×MAC) UDP-broadcast на порт 9
   (опційно — на заданий IP). Надсилає **main**. MAC береться зі списку агентів
   в `.env` main.
2. **Вимкнення сервера** — `hostcmd.sh poweroff` → `systemctl poweroff`;
   якщо systemctl не може дістатися до systemd хоста (напр., Snap Docker),
   fallback — системний виклик `reboot(2)` RB_POWER_OFF (потрібен CAP_SYS_BOOT).
3. **Ребут сервера** — `hostcmd.sh reboot` → `systemctl reboot`; fallback —
   `reboot(2)` RB_AUTOBOOT (CAP_SYS_BOOT).
4. **Контейнери** — статичний білий список у `.env` agent
   (`MANAGED_CONTAINERS`). Дії: стан (список), start / stop / restart.
   `hostcmd.sh` перевіряє назву контейнера за білим списком перед викликом.
5. **Телеметрія** (інтервал конфігурується, за замовчуванням 1 с):
   - `amd-smi monitor` (GPU: сирі дані + розбір полів) — еквівалент
     `sudo watch -n 1 amd-smi monitor` (`watch` потребує TTY, тому реалізовано
     періодичним викликом);
   - температури CPU — sysfs `thermal_zone*`;
   - RAM — `/proc/meminfo` (total/available/used/%);
   - SWAP — `/proc/meminfo` (total/free/used/%);
   - load average та uptime.

## 4. Безпека

1. **mTLS між main і agent**: спільний self-signed сертифікат з SAN
   (генерується `tools/gen-certs.sh`), монтування read-only; з'єднання без
   клієнтського сертифіката відхиляється. Ключі генеруються на хості скриптом
   (openssl) і потрапляють в контейнер лише готовими, у volume.
2. **Ідентифікація**: agent надсилає `hello` з ім'ям та спільним токеном;
   main перевіряє токен за константний час (`hmac.compare_digest`) та те, що
   ім'я є у відомому списку агентів.
3. **Веб-панель**: лише HTTPS; статичний API-токен (`X-API-Key`, порівняння
   за константний час); rate-limiting на дії; SSE для live-оновлень.
4. **Жодного shell-довільності**: `hostcmd.sh` — фіксований `case`-диспетчер
   (без `sh -c` від вводу користувача, без wildcard-аргументів); agent викликає
   його через `subprocess` без `shell=True`.
5. **Ізоляція agent**: лише необхідні монти (docker-сокет, systemd
   private-сокет + маркер `/run/systemd/system`, GPU-пристрої) та лише
   `CAP_SYS_BOOT` (для fallback `reboot(2)`); `systemctl` ходить до PID 1
   хоста напряму через private-сокет (без D-Bus/polkit), а якщо сокет не є
   живим (напр., Snap Docker) — `reboot(2)` питає ядро напряму.
6. **Docker**: agent керує лише контейнерами зі свого білого списку
   (`hostcmd.sh` відхиляє іншу назву).
7. **Agent без вхідних портів**: лише вихідне з'єднання з main; main —
   єдиний слухач.
8. **Аудит-лог**: main логує кожну дію (час, agent, дія, результат) —
   JSON-рядки.
9. **Таємниці** (сертифікати, токени) — лише у змонтованих файлах / `.env`,
   не в образі.
10. **Мінімальні залежності хостів**: main — лише Docker; agent — лише Docker
    (+ `amd-smi` для GPU). Нічого додаткового не встановлюється.

## 5. Конфігурація

Все — через `.env` для docker compose (compose-файли читають змінні з `.env`).

### 5.1. main — `deploy/main/.env`

```dotenv
# Веб-панель (HTTPS) та канал керування (mTLS-WS, слухач)
WEB_PORT=8443
MGMT_PORT=9443
# Токени
#   API_TOKEN  — захист веб/JSON API/SSE (X-API-Key)
#   AGENT_TOKEN — спільний токен агентів (перевіряється з іменем по mTLS)
API_TOKEN=змініть-це-токен-веб
AGENT_TOKEN=змініть-це-спільний-токен
# Список агентів: кількість + NAME/MAC/IP для кожного (i починається з 1).
# MAC потрібен для WoL; IP — необов'язковий (адреса WoL, якщо вказано).
AGENTS_COUNT=2
AGENT_1_NAME=alpha
AGENT_1_MAC=AA:BB:CC:DD:EE:FF
AGENT_1_IP=192.168.1.21
AGENT_2_NAME=beta
AGENT_2_MAC=11:22:33:44:55:66
AGENT_2_IP=192.168.1.22
```

Токени — довільні випадкові рядки, наприклад: `openssl rand -hex 32`.

Сертифікати монтує compose-файл (`./certs` → `/certs`, `CERT_DIR` задано там);
мережа `host` теж задається в compose (щоб WoL broadcast дійшов до LAN).

### 5.2. agent — `deploy/agent/.env`

```dotenv
# Адреса main (mTLS-слухач)
MAIN_HOST=192.168.1.20
MAIN_PORT=9443
# Ідентифікація (AGENT_NAME має збігатися з AGENT_<i>_NAME в main)
AGENT_NAME=alpha
AGENT_TOKEN=тот-самий-спільний-токен
# Контейнери, якими керуємо (білий список, через кому)
CONTAINERS=nginx,postgres
# Інтервал телеметрії (сек)
TELEMETRY_INTERVAL=1.0
# Docker-сокет хоста (для Snap Docker: /var/snap/docker/current/docker.sock)
DOCKER_SOCK=/var/run/docker.sock
```

Сертифікати монтує compose-файл (`./certs` → `/certs`); мережа `host`,
`pid: host` та сокети systemd/docker задаються в compose.

## 6. Розгортання

### 6.1. Генерація сертифікатів (один раз)

```bash
tools/gen-certs.sh ./certs <MAIN_HOST>
```

Створює `certs/cert.key` + `certs/cert.crt` (self-signed, SAN: `MAIN_HOST`,
`localhost`, `127.0.0.1`; EKU: serverAuth + clientAuth).

### 6.2. Main-сервер

1. Копіює `deploy/main/docker-compose.yml` + `deploy/main/.env.example`
   (або клонує репозиторій).
2. `tools/gen-certs.sh ./certs <MAIN_HOST>`.
3. Редагує `.env` (токени, список агентів, MAC).
4. `docker compose up -d`.

### 6.3. Agent-сервер (кожен)

1. Копіює `deploy/agent/docker-compose.yml` + `deploy/agent/.env.example`.
2. Копіює `certs/cert.crt` + `certs/cert.key` з main в `./certs/`.
3. Редагує `.env` (`MAIN_HOST`, `AGENT_NAME`, `AGENT_TOKEN`,
   `MANAGED_CONTAINERS`, `DOCKER_SOCK`).
4. `docker compose up -d`.

   Вимога: на хості працює systemd (compose монтує `/run/systemd/private`
   та маркер `/run/systemd/system`).

### 6.4. Snap Docker

Snap Docker ізолює мережу та змінює шлях сокета. Для підтримки:
- `DOCKER_SOCK=/var/snap/docker/current/docker.sock` в `.env` agent.
- `NETWORK_MODE=host` для WoL (Snap Docker підтримує host-мережу; broadcast
  може потребувати додаткових налаштувань — див. README).

## 7. Обмеження (свідомі)

- Agent виконує команди лише в контексті свого контейнера; для керування
  живим хостом контейнер отримує `pid: host` + монти systemd/docker-сокетів.
- Якщо в системі немає thermal zones, поле температур CPU буде порожнім.
- WoL працює, лише якщо main у тій самій L2-мережі (або є маршрутизація
  broadcast).
- `amd-smi` має бути встановлений на хості agent для GPU-телеметрії
  (інакше поле gpu буде порожнім — це не помилка).
