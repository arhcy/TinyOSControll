# TinyOSControll

**Мови:** [English](README.md) | [Українська](README.uk.md)

Мережевий інструмент керування серверами: веб-панель на центральній машині
(**main**) керує кількома віддаленими серверами (**agent**) — Wake-on-LAN,
вимкнення, ребут, керування заздалегідь визначеними Docker-контейнерами та
жива телеметрія (CPU / RAM / SWAP / GPU).

Весь код — **Python** та **bash**. Без SSH, без виконання довільних команд.
Деталі — у [`docs/SPEC.md`](docs/SPEC.md) та [`docs/PLAN.md`](docs/PLAN.md).

## Архітектура

- **main** — контейнер: веб-інтерфейс (HTTPS) + mTLS-WS-сервер, що спілкується
  з агентами + надсилає WoL.
- **agent** — контейнер (кілька на різних серверах): один демон +
  bash-диспетчер системних команд. Ініціює вихідне mTLS-з'єднання з main.

З'єднання — **mTLS-WebSocket** (спільний self-signed сертифікат), TLS ≥ 1.2.
Agent не відкриває вхідних портів.

## Встановлення

### 0. Генерація сертифіката (один раз, на main)

```bash
tools/gen-certs.sh ./certs <MAIN_HOST>
# наприклад:
tools/gen-certs.sh ./certs 192.168.1.20
```

Створює `certs/cert.key` + `certs/cert.crt`.

### 1. Main

```bash
# скопіюйте deploy/main/docker-compose.yml та .env.example в робочий каталог
cp deploy/main/docker-compose.yml .
cp deploy/main/.env.example .env
# редагуйте .env: WEB_TOKEN, AGENT_TOKEN, AGENTS, AGENT_MAC_*
docker compose up -d
# веб-панель: https://<main-host>:8443  (токен — WEB_TOKEN)
```

### 2. Agent (кожен сервер)

```bash
cp deploy/agent/docker-compose.yml .
cp deploy/agent/.env.example .env
# скопіюйте сертифікати з main:
mkdir -p certs && cp <main>/certs/cert.crt <main>/certs/cert.key certs/
# редагуйте .env: MAIN_HOST, AGENT_NAME, AGENT_TOKEN, MANAGED_CONTAINERS, DOCKER_SOCK
docker compose up -d
```

Користувач може також просто клонувати репозиторій на обидві машини.

### Snap Docker

Snap Docker ізолює мережу та змінює шлях сокета:

- В `.env` agent: `DOCKER_SOCK=/var/snap/docker/current/docker.sock`.
- Для WoL: `NETWORK_MODE=host` (Snap Docker підтримує host-мережу). Якщо
  broadcast не доходить до LAN, перевірте мережеві налаштування snap.

## Функції

- **Wake-on-LAN** по MAC (надсилає main).
- **Вимкнення** / **ребут** сервера.
- **Контейнери**: стан, start / stop / restart (білий список у `.env` agent).
- **Телеметрія** (раз на секунду): `amd-smi monitor`, температури CPU,
  RAM, SWAP, load, uptime.

## Локальне тестування (без реальних серверів)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q
```

Див. `docs/PLAN.md` розділ 3.2 для сценарію локальної інтеграції.

## Структура

```
common/    # protocol, tls, wol (спільний код)
agent/     # agent.py, hostcmd.sh, entrypoint.sh, Dockerfile
main/      # main.py, web/, Dockerfile
deploy/    # docker-compose.yml + .env.example для main і agent
tools/     # gen-certs.sh
tests/     # модульні + локальна інтеграція
docs/      # SPEC.md, PLAN.md
```
