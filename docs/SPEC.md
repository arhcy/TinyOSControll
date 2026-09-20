# OS Control — специфікація

Локальний інструмент керування цільовим Ubuntu-сервером з контрольного Ubuntu-сервера:
веб-панель, телеметрія температур, Wake-on-LAN, вимкнення, керування заздалегідь
визначеними Docker-контейнерами.

## 1. Архітектура

Два хости:

| Хост | Компоненти |
|---|---|
| **Control** (сервер A) | контейнер `osagent-controller` (Python) — веб-панель (HTTPS) + канал керування + WoL |
| **Target** (сервер B) | 3 systemd-демони (Python, stdlib): `osagent-agent`, `osagent-executor`, `osagent-docker-proxy` |

Ключові рішення:

- **Агент ініціює з'єднання** з контролером (вихідне з'єднання). Target не відкриває
  жодних вхідних портів — його фаєрвол може бути закритим повністю.
- **Одна двостороння mTLS-сесія** несе і телеметрію (agent→controller), і запити
  керування (controller→agent).
- **WoL надсилає контролер** (магічний пакет має йти по LAN, а вимкнена машина
  виконувати команди не може). Контролер працює в `network_mode: host`, щоб
  broadcast дійшов до мережі.
- **`osagent-executor`** — хост-демон (systemd, користувач `osagent`), який виконує
  лише жорстко визначений набір команд. Агент спілкується з ним через unix-сокет.
- **`osagent-docker-proxy`** — хост-демон (systemd, root), який проксі-є лише
  allowlist-частина Docker Engine API (containers) на локальний unix-сокет.
  Агент не торкається справжнього docker-сокета.
- **Демони — Python 3, лише стандартна бібліотека** (без pip-пакетів).
  Go-реалізація (`cmd/@, `internal/@) збережена в репозиторії як
  reference-реалізація з тестами; у розгортанні не використовується.
- **Усе, що потрапляє на хости, збирається в контейнері** (build-стадія, розділ 6):
  хост Control потребує лише Docker, хост Target — лише стандартний Ubuntu + Docker.

## 2. Протокол

- JSON-повідомлення поверх **WebSocket**, **mTLS** (спільна локальна CA), TLS ≥ 1.2.
- **Без SSH, без виконання довільних команд** — лише фіксований набір дій.

Повідомлення:

```json
{"type":"request","id":"…","action":"shutdown"}
{"type":"response","id":"…","ok":true,"payload":{...}}
{"type":"telemetry","payload":{"ts":"…","cpu":[...],"ram":{...},"gpu":{...}}}
```

Дії керування: `health`, `shutdown`, `containers.list`, `containers.action`.

## 3. Функції

1. **Wake-on-LAN** — магічний пакет (6×FF + 16×MAC) UDP-broadcast на порт 9
   (опційно — на заданий IP). MAC перевіряється за формою.
2. **Вимкнення сервера** — `systemctl poweroff` через executor (sudo).
3. **Контейнери** — статичний білий список у конфізі agent. Дії: стан
   (список), start / stop / restart. Доступ до Docker — лише через
   `osagent-docker-proxy` з одним дозволеним ендпоінтом `containers`.
4. **Телеметрія** (інтервал конфігурується, за замовчуванням 1 с — еквівалент
   `watch -n 1`; `watch` потребує TTY, тому реалізовано періодичним викликом):
   - `amd-smi monitor` (GPU: температура, завантаження, пам'ять, годинники + сирі дані);
   - температури CPU — sysfs thermal zones;
   - RAM — `/proc/meminfo` (total/available/used/%);
   - load average та uptime хоста.

## 4. Безпека (допрацьовано)

1. **mTLS між контролером і агентом**: локальна CA, сертифікати з SAN,
   монтування read-only; без сертифіката клієнта з'єднання відхиляється.
   Ключі генеруються **в build-контейнері** (openssl) і потрапляють на хости
   лише готовими, у volume/bundle.
2. **Веб-панель**: лише HTTPS; статичний API-токен (`X-API-Key`, порівняння
   за константний час); rate-limiting на дії; SSE для live-оновлень.
3. **Жодного shell**: executor виконує лише таблицю точних `argv`
   (subprocess.run без shell), без `sh -c`, без wildcard-аргументів.
4. **Ідентифікація клієнта executor'а — `SO_PEERCRED`** (uid з'єднання,
   перевіряється ядром): агент працює під uid `osagent` (10001), токенів
   для сокету немає — нічого викачувати.
5. **sudo**: окремий системний користувач `osagent`, точний allowlist у
   `/etc/sudoers.d/osagent` (повні шляхи, без wildcard, NOPASSWD лише для
   двох команд).
6. **Агент як systemd-сервіс**: non-root (user `osagent`),
   `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`,
   `RestrictAddressFamilies`.
7. **Docker**: тільки через `osagent-docker-proxy` (systemd, root,
   `SupplementaryGroups=docker`, `NoNewPrivileges`, `ProtectSystem=strict`)
   з ендпоінтом `containers` (без images/networks/volumes); agent бачить
   лише контейнери зі свого білого списку.
8. **Таргет без вхідних портів**: агент лише вихідно з'єднується з контролером.
9. **Аудит-лог**: кожну дію (WoL, shutdown, контейнер) логується
   (час, IP, дія, результат) — JSON-логи.
10. **Таємниці** (токен, сертифікати) — лише у змонтованих файлах,
    не в образі; bundle має `MANIFEST` (sha256) — інсталеєр перевіряє
    цілісність перед встановленням.
11. **Мінімальні залежності хостів**: Control — лише Docker;
    Target — стандартний Ubuntu (python3, systemd, coreutils, sudo) + Docker.
    Нічого додаткового не встановлюється.

## 5. Конфігурація

Конфіги — **JSON** (Python-демони, stdlib). Генеруються build-стадією
(контролер) та інсталятором (агент).

`controller.json` (у volume, читається контейнером контролера):

```json
{
  "listen": {"web": ":8443", "management": ":9443"},
  "api_token": "…",
  "wol": {"mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.1.10", "port": 9},
  "telemetry": {"history_minutes": 60},
  "tls": {
    "ca": "/out/keys/ca.crt",
    "cert": "/out/keys/controller.crt",
    "key": "/out/keys/controller.key"
  }
}
```

`agent.json` (на Target, `/etc/osagent/agent.json`, створює `install.sh`):

```json
{
  "controller": {"url": "wss://192.168.1.20:9443"},
  "executor": {"socket": "/run/osagent/executor.sock"},
  "docker": {
    "endpoint": "unix:///run/osagent/docker.sock",
    "containers": ["nginx", "postgres"]
  },
  "telemetry": {"interval": 1.0},
  "tls": {
    "ca": "/etc/osagent/certs/ca.crt",
    "cert": "/etc/osagent/certs/agent.crt",
    "key": "/etc/osagent/certs/agent.key"
  }
}
```

## 6. Розгортання

### 6.1. Build-стадія (контейнер, на Control)

`deploy/build/` — Dockerfile (python:3.12-slim + openssl) і `build.sh`,
який **всередині контейнера**:

1. генерує TLS-ключі: CA (RSA-4096, 10 років) + controller (SAN: hostname,
   localhost, IP) + agent (RSA-2048, 825 днів);
2. пакує Python-демони з `daemons/` і робить "білд" — перевірку синтаксису
   (python3 -m py_compile);
3. генерує `config/controller.json` (api_token — openssl rand -hex 24,
   якщо не задано) та шаблон `config/agent.json`;
4. копіює systemd-юніти, sudo-allowlist і `install.sh`;
5. пише `BUNDLE_INFO.txt` (параметри + API-токен) і `MANIFEST` (sha256).

Усе з'являється у **монтованому docker volume `osagent-build`** (`/out`):

```
osagent-build:
  keys/        ca.{crt,key} controller.{crt,key} agent.{crt,key}
  daemons/     osagent_*.py wslib.py web/
  config/      controller.json agent.json
  target/      osagent-{agent,executor,docker-proxy}.service sudoers.d-osagent
  install.sh   MANIFEST  BUNDLE_INFO.txt
```

Запуск: docker compose -f deploy/build/docker-compose.yml up --build
(обов'язкові env: `WEB_HOSTNAME`, `WEB_IP`, `WOL_MAC`).

### 6.2. Control-сервер

- Build-стадія (6.1) — один раз (або при зміні параметрів/коду).
- Контролер — контейнер `python:3.12-slim` (non-root uid 10001, read-only,
  `network_mode: host` для WoL), монтує volume `osagent-build` read-only.
  docker compose -f deploy/controller/docker-compose.yml up -d.

### 6.3. Target-сервер

- Bundle з volume копіюється на Target (docker cp + scp, див. README).
- **sudo bash install.sh --controller-url … --containers …** встановлює:
  користувача `osagent` (uid 10001), sudo-allowlist, демони в `/opt/osagent`,
  сертифікати в `/etc/osagent/certs`, `agent.json`, 3 systemd-юніти —
  і запускає сервіси. Без Go, без pip, без додаткових пакетів.

### 6.4. Мова

- **Python 3 (stdlib)** — production-демони (`daemons/`): один код для
  обох хостів, без збірки, без залежностей.
- **Go** (`cmd/@, `internal/@) — reference-реалізація з модульними тестами
  (go test ./...); у розгортанні не використовується.

Детальні інструкції — у `README.md`.

## 7. Обмеження (свідомі)

- Одна цільова машина на контролер (1:1); розширення на кілька агентів —
  наступна ітерація.
- Якщо в системі немає thermal zones (рідкісні материнські плати), поле
  температур CPU буде порожнім.
- WoL працює, лише якщо контролер у тій самій L2-мережі (або є маршрутизація
  broadcast).
- `amd-smi` має бути встановлений на Target для GPU-телеметрії (інакше поле
  gpu буде порожнім — це не помилка інсталяції).
