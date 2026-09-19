# OS Control

Локальний інструмент керування цільовим Ubuntu-сервером з контрольного:
веб-панель, телеметрія температур, Wake-on-LAN, вимкнення, керування
визначеним у конфізі набором Docker-контейнерів.

- Спека: [docs/SPEC.md](docs/SPEC.md)
- План виконання та тестування: [docs/PLAN.md](docs/PLAN.md)

## Компоненти

| Компонент | Де | Що робить |
|---|---|---|
| osagent-controller | Docker, Control | веб-панель (HTTPS), канал керування, WoL |
| osagent-agent | Docker, Target | виконує дії, збирає телеметрію, з'єднується вихідно |
| osagent-executor | systemd, Target | allowlist-команди хоста (sudo), unix-сокет + SO_PEERCRED |
| docker-socket-proxy | Docker, Target | обмежений Docker API (лише containers) |

Мова: Go. Протокол: JSON over WebSocket, mTLS (без SSH).

---

# Запуск під Dockerом

Усі контейнерні частини запускаються через **Docker Compose**.
Репозиторій завантажується з GitHub на обидва сервери.

**Спільні вимоги:** Ubuntu 22.04+, Docker Engine + Compose v2, git.
Якщо Docker ще немає:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # вийти й увійти в сесію
```

Нижче — інструкції для кожного сервера окремо.
**Спершу налаштовується Control, потім Target** (агенту потрібні
сертифікати та панель, які з'являються на Control).

---

## Сервер 1: Control

### 1.1. Клон репозиторію

```bash
git clone https://github.com/<owner>/osagent.git
cd osagent
```

### 1.2. Сертифікати (CA + controller + agent)

```bash
# аргументи: <каталог> <hostname панелі> <IP control-сервера>
bash deploy/scripts/gen-certs.sh deploy/controller/certs ctrl 192.168.1.20
```

- `ctrl` — ім'я хоста, за яким відкриватимете панель (з'явиться в SAN сертифіката);
- `192.168.1.20` — IP control-сервера (агент перевірятиме його при mTLS).

### 1.3. Конфіг

```bash
cp deploy/controller/config/controller.yaml.example deploy/controller/config/controller.yaml
openssl rand -hex 24    # результат — значення api_token
```

Відкрийте `deploy/controller/config/controller.yaml` і заповніть:

| Поле | Що вписати |
|---|---|
| `api_token` | токен з `openssl rand -hex 24` (вхід у панель) |
| `wol.mac` | MAC-адреса **Target**-сервера (для Wake-on-LAN) |
| `wol.ip` | IP Target-сервера (напрямлений WoL, опційно) |

### 1.4. Запуск

```bash
docker compose -f deploy/controller/docker-compose.yml up -d --build
```

### 1.5. Перевірка

```bash
docker compose -f deploy/controller/docker-compose.yml ps
docker compose -f deploy/controller/docker-compose.yml logs -f
curl -sk https://localhost:8443/api/status -H "X-API-Key: <api_token>"
```

Відкрийте `https://<control-host>:8443` у браузері і введіть api_token.
Поки Target не підключений, поле `agent_online` буде `false` — це нормально.

> **Альтернатива одним скриптом** (робить 1.2–1.4 автоматично,
> згенерує конфіг із аргументами):
>
> ```bash
> bash deploy/scripts/install-controller.sh \
>   --wol-mac AA:BB:CC:DD:EE:FF --wol-ip 192.168.1.10 \
>   --web-hostname ctrl --web-ip 192.168.1.20
> ```

---

## Сервер 2: Target

### 2.1. Клон репозиторію

```bash
git clone https://github.com/<owner>/osagent.git
cd osagent
```

### 2.2. Сертифікати з Control-сервера

Скопіюйте три файли з `deploy/controller/certs/` на Control у
`deploy/target/certs/` на Target:

```bash
mkdir -p deploy/target/certs
scp <control>:/path/to/osagent/deploy/controller/certs/ca.crt     deploy/target/certs/
scp <control>:/path/to/osagent/deploy/controller/certs/agent.crt  deploy/target/certs/
scp <control>:/path/to/osagent/deploy/controller/certs/agent.key  deploy/target/certs/
```

### 2.3. Executor (єдиний компонент поза контейнерами)

Executor — systemd-демон на хості: виконує allowlist-команди
(`systemctl poweroff`, `amd-smi monitor`) через точний sudo-allowlist
і перевіряє клієнта за SO_PEERCRED.

```bash
# користувач osagent з uid 10001 (має збігатися з user: у compose агента)
sudo useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin osagent

# sudo-allowlist (лише дві команди)
sudo install -m 0440 deploy/target/sudoers.d-osagent /etc/sudoers.d/osagent
sudo visudo -cf /etc/sudoers.d/osagent

# бинар (з dist/ у репо або збірка з Go):
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" \
  -o dist/osagent-executor ./cmd/osagent-executor
sudo install -m 0755 dist/osagent-executor /usr/local/bin/osagent-executor

# systemd-юніт
sudo install -m 0644 deploy/target/osagent-executor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now osagent-executor
sudo systemctl status osagent-executor
```

### 2.4. Конфіг агента

```bash
cp deploy/target/config/agent.yaml.example deploy/target/config/agent.yaml
```

Відкрийте `deploy/target/config/agent.yaml` і заповніть:

| Поле | Що вписати |
|---|---|
| `controller.url` | `wss://<control-host>:9443` або `wss://<control-ip>:9443` (hostname/IP має бути в SAN сертифіката) |
| `docker.containers` | список імен контейнерів, якими керуємо (напр. `nginx`, `postgres`) |

### 2.5. Запуск

```bash
docker compose -f deploy/target/docker-compose.yml up -d --build
```

Піднімаються два контейнери: `docker-proxy` (обмежений Docker API) і
`agent` (non-root, read-only, з'єднується вихідно до Control).

### 2.6. Перевірка

```bash
docker compose -f deploy/target/docker-compose.yml ps
docker compose -f deploy/target/docker-compose.yml logs -f agent
```

У логах агента має з'явитися `connected to controller`. На панелі
Control `agent_online` стане `true`, з'явиться телеметрія та список
контейнерів.

> **Альтернатива одним скриптом** (робить 2.3–2.5 автоматично,
> сертифікати з 2.2 все одно треба скопіювати вручну):
>
> ```bash
> bash deploy/scripts/install-target.sh \
>   --controller-url wss://192.168.1.20:9443 --containers nginx,postgres
> ```

---

## Оновлення

```bash
# на кожному з серверів:
git pull
docker compose -f deploy/<controller|target>/docker-compose.yml up -d --build
```

Для оновлення executor-бинара на Target повторіть збірку з 2.3 і
`sudo systemctl restart osagent-executor`.

## Зупинка

```bash
docker compose -f deploy/controller/docker-compose.yml down   # Control
docker compose -f deploy/target/docker-compose.yml down       # Target
sudo systemctl stop osagent-executor                          # Target (за потреби)
```

## Типові проблеми

| Симптом | Що перевірити |
|---|---|
| `agent_online: false`, в логах агента `dial failed` | `controller.url` у agent.yaml; SAN сертифіката (hostname/IP); що панель на Control запущена |
| `connection refused` / `rejected connection` в логах executor | uid користувача `osagent` на хості має бути **10001** (`id -u osagent`) |
| WoL не будить | `wol.mac` у controller.yaml; WoL увімкнений у BIOS Target; вихідний UDP 9 з Control |
| Керування контейнерами не працює | контейнери мають існувати на Target; `docker-proxy` у `ps`; ім'я в `docker.containers` |

---

# Docker Compose файли

Control — `deploy/controller/docker-compose.yml`:

```yaml
name: osagent-controller
services:
  controller:
    build:
      context: ../..
      dockerfile: deploy/Dockerfile.controller
    image: osagent-controller:local
    restart: unless-stopped
    network_mode: host   # WoL broadcast must reach the LAN
    read_only: true
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    volumes:
      - ./config/controller.yaml:/etc/osagent/controller.yaml:ro
      - ./certs:/etc/osagent/certs:ro
    tmpfs:
      - /tmp:size=16m
```

Target — `deploy/target/docker-compose.yml`:

```yaml
name: osagent-target
services:
  docker-proxy:
    image: tecnativa/docker-socket-proxy:latest
    restart: unless-stopped
    command: ["containers=1", "-l", "unix:///var/run/docker-proxy/docker.sock"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - docker-proxy-sock:/var/run/docker-proxy
    networks: [osagent]

  agent:
    build:
      context: ../..
      dockerfile: deploy/Dockerfile.agent
    image: osagent-agent:local
    restart: unless-stopped
    user: "10001:10001"   # must match the osagent uid on the host (SO_PEERCRED check)
    read_only: true
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    volumes:
      - ./config/agent.yaml:/etc/osagent/agent.yaml:ro
      - ./certs:/etc/osagent/certs:ro
      - /run/osagent:/run/osagent:ro
      - docker-proxy-sock:/var/run/docker-proxy:ro
    tmpfs:
      - /tmp:size=16m
    networks: [osagent]

volumes:
  docker-proxy-sock:

networks:
  osagent:
```

---

## Розробка

- go build ./... ; go test ./... ; go vet ./...
- GOOS=linux GOARCH=amd64 go build -o dist/osagent-executor ./cmd/osagent-executor

## Порти

| Хост | Порт | Призначення |
|---|---|---|
| Control | 8443/tcp | веб-панель (HTTPS) |
| Control | 9443/tcp | mTLS WS (туди з'єднується агент) |
| Target | — | вхідних портів немає |

## Безпека

mTLS, жодного shell, точний sudo-allowlist, SO_PEERCRED-перевірка,
non-root read-only контейнери, docker-socket-proxy, аудит-лог —
деталі у розділі 4 спеки.
