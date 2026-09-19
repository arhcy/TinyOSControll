# OS Control — специфікація

Локальний інструмент керування цільовим Ubuntu-сервером з контрольного Ubuntu-сервера:
веб-панель, телеметрія температур, Wake-on-LAN, вимкнення, керування заздалегідь
визначеними Docker-контейнерами.

## 1. Архітектура

Два хости:

| Хост | Компоненти |
|---|---|
| **Control** (сервер A) | контейнер `osagent-controller` — веб-панель (HTTPS) + канал керування |
| **Target** (сервер B) | контейнер `osagent-agent` + хост-демон `osagent-executor` (systemd) + контейнер `docker-socket-proxy` |

Ключові рішення:

- **Агент ініціює з'єднання** з контролером (вихідне з'єднання). Target не відкриває
  жодних вхідних портів — його фаєрвол може бути закритим повністю.
- **Одна двостороння mTLS-сесія** несе і телеметрію (agent→controller), і запити
  керування (controller→agent).
- **WoL надсилає контролер** (магічний пакет має йти по LAN, а вимкнена машина
  виконувати команди не може). Контролер працює в `network_mode: host`, щоб
  broadcast дійшов до мережі.
- **`osagent-executor`** — невеликий хост-демон (systemd, окремий користувач
  `osagent`), який виконує лише жорстко визначений набір команд. Контейнер
  agent спілкується з ним через unix-сокет.

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
   `docker-socket-proxy` з одним дозволеним ендпоінтом `containers`.
4. **Телеметрія** (інтервал конфігурується, за замовчуванням 1 с — еквівалент
   `watch -n 1`; `watch` потребує TTY, тому реалізовано періодичним викликом):
   - `amd-smi monitor` (GPU: температура, завантаження, пам'ять, годинники + сирі дані);
   - температури CPU — sysfs thermal zones;
   - RAM — `/proc/meminfo` (total/available/used/%);
   - load average та uptime хоста.

## 4. Безпека (допрацьовано)

1. **mTLS між контролером і агентом**: локальна CA, сертифікати з SAN,
   монтування read-only; без сертифіката клієнта з'єднання відхиляється.
2. **Веб-панель**: лише HTTPS; статичний API-токен (`X-API-Key`, порівняння
   за константний час); rate-limiting на дії; SSE для live-оновлень.
3. **Жодного shell**: executor виконує лише таблицю точних `argv`
   (`exec.Command`), без `sh -c`, без wildcard-аргументів.
4. **Ідентифікація клієнта executor'а — `SO_PEERCRED`** (uid з'єднання,
   перевіряється ядром): агент має запускатись під uid `osagent` (10001),
   токенів для сокету немає — нічого викачувати.
5. **sudo**: окремий системний користувач `osagent`, точний allowlist у
   `/etc/sudoers.d/osagent` (повні шляхи, без wildcard, NOPASSWD лише для
   двох команд).
6. **Контейнер agent**: non-root (uid 10001), `read_only` rootfs, `cap_drop: ALL`,
   `no-new-privileges`, без `privileged`.
7. **Docker**: тільки через socket-proxy з ендпоінтом `containers=1`
   (без images/networks/volumes); agent бачить лише контейнери зі свого
   білого списку.
8. **Таргет без вхідних портів**: агент лише вихідно з'єднується з контролером.
9. **Аудит-лог**: кожну дію (WoL, shutdown, контейнер) логується
   (час, IP, дія, результат) — JSON-логи.
10. **Таємниці** (токен, сертифікати) — лише у змонтованих файлах, не в образі.

## 5. Конфігурація

`controller.yaml`:

```yaml
listen:
  web: ":8443"        # веб-панель (HTTPS)
  management: ":9443" # mTLS WS-сервер (туди з'єднується агент)
api_token: "…"       # токен веб-API
agent:
  url: "wss://192.168.1.10:9443"   # не використовується (агент сам з'єднується),
                                   # залишено для інформації
wol:
  mac: "AA:BB:CC:DD:EE:FF"
  ip: "192.168.1.10"   # опційно, directed packet
  port: 9
telemetry:
  history_minutes: 60
tls:
  ca: /etc/osagent/certs/ca.crt
  cert: /etc/osagent/certs/controller.crt
  key: /etc/osagent/certs/controller.key
```

`agent.yaml`:

```yaml
controller:
  url: "wss://192.168.1.20:9443"
executor:
  socket: /run/osagent/executor.sock
docker:
  endpoint: "unix:///var/run/docker-proxy/docker.sock"
  containers:            # білий список, вручну
    - nginx
    - postgres
telemetry:
  interval: 1s
tls:
  ca: /etc/osagent/certs/ca.crt
  cert: /etc/osagent/certs/agent.crt
  key: /etc/osagent/certs/agent.key
```

## 6. Розгортання

- Control: `docker compose` (host-мережа) + сертифікати.
- Target: користувач `osagent` + sudoers + `osagent-executor` (systemd)
  + `docker compose` (agent + docker-proxy).
- Сертифікати генерує `deploy/scripts/gen-certs.sh` (CA + controller + agent).
- Мова: **Go** (статичні бинарі, малі distroless-образи, горучі конкурентні
  цикли телеметрії). Деталі — у `README.md` та `docs/PLAN.md`.

## 7. Обмеження (свідомі)

- Одна цільова машина на контролер (1:1); розширення на кілька агентів —
  наступна ітерація.
- Якщо в системі немає thermal zones (рідкісні материнські плати), поле
  температур CPU буде порожнім.
- WoL працює, лише якщо контролер у тій самій L2-мережі (або є маршрутизація
  broadcast).
