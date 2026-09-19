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

## Швидкий старт (Docker Compose)

Вимоги: Ubuntu 22.04+, Docker Engine + Compose v2, git.
Репозиторій завантажується з GitHub на обидва сервери.

### 1. Control-сервер

```bash
git clone https://github.com/<owner>/osagent.git && cd osagent
# CA + сертифікати (controller, agent):
bash deploy/scripts/gen-certs.sh deploy/controller/certs ctrl 192.168.1.20
# конфіг (api_token: openssl rand -hex 24):
cp deploy/controller/config/controller.yaml.example deploy/controller/config/controller.yaml
# заповніть у controller.yaml: api_token, wol.mac, wol.ip
docker compose -f deploy/controller/docker-compose.yml up -d --build
```

Панель: `https://<control-host>:8443`, вхід — api_token.

### 2. Target-сервер

```bash
git clone https://github.com/<owner>/osagent.git && cd osagent
# сертифікати з control-сервера (deploy/controller/certs/):
mkdir -p deploy/target/certs
cp ca.crt agent.crt agent.key deploy/target/certs/
# створює osagent-юзера (uid 10001), sudo-allowlist, executor (systemd),
# агент-конфіг і піднімає compose-стек:
bash deploy/scripts/install-target.sh \
  --controller-url wss://192.168.1.20:9443 --containers nginx,postgres
```

### Docker Compose файли

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

Executor — єдиний компонент поза контейнерами (потрібен sudo та
SO_PEERCRED на хості): `deploy/target/osagent-executor.service` +
`deploy/target/sudoers.d-osagent`, встановлює `install-target.sh`.

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
