# OS Control

Локальний інструмент керування цільовим Ubuntu-сервером з контрольного:
веб-панель, телеметрія температур, Wake-on-LAN, вимкнення, керування
визначеними у конфізі набором Docker-контейнерів.

- Спека: `docs/SPEC.md`
- План виконання та тестування: `docs/PLAN.md`

## Компоненти

| Компонент | Де | Що робить |
|---|---|---|
| osagent-controller | Docker, Control | веб-панель (HTTPS), канал керування, WoL |
| osagent-agent | systemd, Target | виконує дії, збирає телеметрію, з'єднується вихідно |
| osagent-executor | systemd, Target | allowlist-команди хоста (sudo), unix-сокет + SO_PEERCRED |
| osagent-docker-proxy | systemd, Target | обмежений Docker API (лише containers) |

Демони — **Python 3, лише стандартна бібліотека** (без pip, без збірки).
Протокол: JSON over WebSocket, mTLS (без SSH). Go-код у репозиторії —
reference-реалізація з тестами, у розгортанні не використовується.

## Як влаштована інсталяція

1. **Build-стадія в контейнері** (на Control): контейнер `deploy/build/`
   генерує TLS-ключі (openssl), пакує демони з `daemons/`, перевіряє
   синтаксис ("білд"), генерує конфіги та інсталяційний скрипт. Усе
   з'являється у **монтованому docker volume `osagent-build`**:
   ключі, демони, конфіги, юніти, `install.sh`, MANIFEST (sha256).
2. **Control**: контейнер контролера читає все з цього ж volume (read-only).
3. **Target**: bundle з volume копіюється на сервер, і **sh-скрипт
   `install.sh`** встановлює три демони як systemd-сервіси.

Хостам не потрібно нічого встановлювати понад стандартне:
Control — Docker, Target — стандартний Ubuntu (python3, systemd) + Docker.

## Вимоги

| Сервер | Потребує |
|---|---|
| Control | Ubuntu 22.04+, Docker Engine + Compose v2, git |
| Target | Ubuntu 22.04+, Docker Engine, python3 (3.8+, stdlib), systemd |

Якщо Docker ще немає (Control і Target):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # вийти й увійти в сесію
```

---

# Сервер 1: Control

## 1.1. Клон репозиторію

```bash
git clone https://github.com/arhcy/TinyOSControll.git
cd osagent
```

## 1.2. Build-стадія: ключі + демони → volume

```bash
WEB_HOSTNAME=ctrl WEB_IP=192.168.1.20 WOL_MAC=AA:BB:CC:DD:EE:FF \
  docker compose -f deploy/build/docker-compose.yml up --build
```

- `WEB_HOSTNAME` — ім'я хоста, за яким відкриватимете панель (SAN сертифіката);
- `WEB_IP` — IP control-сервера (агент перевірятиме його при mTLS);
- `WOL_MAC` — MAC-адреса **Target**-сервера (для Wake-on-LAN);
- опційно: `WOL_IP`, `API_TOKEN` (інакше згенерується), `CONTROLLER_URL`,
  `CONTAINERS`, `TELEMETRY_INTERVAL`.

У виводі буде рядок **`API token: …`** — збережіть його (він також у
`BUNDLE_INFO.txt` в volume). Після запуску в volume `osagent-build`
з'являються: `keys/`, `daemons/`, `config/`, `target/`, `install.sh`,
`MANIFEST`, `BUNDLE_INFO.txt`.

## 1.3. Запуск контролера

```bash
docker compose -f deploy/controller/docker-compose.yml up -d
```

Контролер — контейнер `python:3.12-slim` (non-root, read-only, host-мережа
для WoL-broadcast), монтує volume `osagent-build` read-only.

## 1.4. Перевірка

```bash
docker compose -f deploy/controller/docker-compose.yml ps
docker compose -f deploy/controller/docker-compose.yml logs -f
curl -sk https://localhost:8443/api/status -H "X-API-Key: <api_token>"
```

Відкрийте `https://<control-host>:8443` у браузері і введіть api_token.
Поки Target не підключений, поле `agent_online` буде `false` — це нормально.

---

# Сервер 2: Target

## 2.1. Експорт bundle з volume (на Control)

```bash
docker create --name osagent-export -v osagent-build:/out osagent-build:local /bin/true
docker cp osagent-export:/out ./target-bundle
docker rm osagent-export
scp -r target-bundle <user>@<target>:/root/
```

## 2.2. Встановлення (sh-скрипт, на Target)

```bash
sudo bash /root/target-bundle/install.sh \
  --controller-url wss://192.168.1.20:9443 \
  --containers nginx,postgres
```

Скрипт (з bundle, згенерований build-стадією) робить усе сам:

- перевіряє цілісність bundle (MANIFEST sha256 + openssl verify сертифіката);
- створює системного користувача `osagent` (uid 10001);
- встановлює демони в `/opt/osagent/daemons`, сертифікати в
  `/etc/osagent/certs`, створює `/etc/osagent/agent.json`;
- встановлює sudo-allowlist (`/etc/sudoers.d/osagent`, лише дві команди);
- встановлює 3 systemd-юніти (`osagent-executor`, `osagent-docker-proxy`,
  `osagent-agent`) і запускає їх;
- перевіряє, що всі сервіси активні.

Опційні аргументи: `--telemetry-interval 1`, `--prefix /opt/osagent`.
Демонтування: `sudo bash install.sh --uninstall`.

## 2.3. Перевірка

```bash
systemctl status osagent-agent osagent-executor osagent-docker-proxy
journalctl -u osagent-agent -f
```

У логах агента має з'явитися `connected to controller`. На панелі Control
`agent_online` стане `true`, з'явиться телеметрія та список контейнерів.

---

## Оновлення

```bash
# Control: оновити код, пересобрати bundle, перезапустити контролер
git pull
WEB_HOSTNAME=ctrl WEB_IP=192.168.1.20 WOL_MAC=AA:BB:CC:DD:EE:FF \
  docker compose -f deploy/build/docker-compose.yml up --build
docker compose -f deploy/controller/docker-compose.yml up -d

# Target: експортувати новий bundle (2.1), скопіювати, перевстановити
sudo bash /root/target-bundle/install.sh \
  --controller-url wss://192.168.1.20:9443 --containers nginx,postgres
```

Перевстановлення ідемпотентне: сервіси зупиняються, файли замінюються,
конфіг `agent.json` перезаписується з аргументами скрипта.

## Зупинка

```bash
docker compose -f deploy/controller/docker-compose.yml down   # Control
sudo bash install.sh --uninstall                              # Target
```

## Типові проблеми

| Симптом | Що перевірити |
|---|---|
| Build не стартує | `WEB_HOSTNAME`, `WEB_IP`, `WOL_MAC` задані? docker compose logs build |
| `agent_online: false`, в логах агента `controller dial failed` | `--controller-url` (hostname/IP має бути в SAN сертифіката); що панель на Control запущена |
| `rejected connection uid=…` в логах executor | uid користувача `osagent` має бути **10001** (`id -u osagent`) |
| WoL не будить | `WOL_MAC` у build; WoL увімкнений у BIOS Target; вихідний UDP 9 з Control |
| Керування контейнерами не працює | контейнери мають існувати на Target; `systemctl status osagent-docker-proxy`; ім'я в `--containers` |
| GPU-телеметрія порожня | `amd-smi` встановлений на Target? (`sudo amd-smi monitor`) |

## Порти

| Хост | Порт | Призначення |
|---|---|---|
| Control | 8443/tcp | веб-панель (HTTPS) |
| Control | 9443/tcp | mTLS WS (туди з'єднується агент) |
| Target | — | вхідних портів немає |

## Безпека

mTLS, жодного shell, точний sudo-allowlist, SO_PEERCRED-перевірка,
hardened systemd-сервіси, docker-proxy з allowlist, аудит-лог, MANIFEST
цілісності bundle — деталі у розділі 4 спеки.

## Розробка

- Production-демони: `daemons/` (Python, stdlib). Перевірка:
  `python3 -m py_compile daemons/*.py`.
- Reference-реалізація (Go): `go build ./...`; `go test ./...`; `go vet ./...`.
