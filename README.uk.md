# TinyOSControll

**Мови:** [English](README.md) | [Українська](README.uk.md)

Мережевий інструмент керування серверами: веб-панель на центральній машині
(**main**) керує кількома віддаленими серверами (**agent**) — Wake-on-LAN,
вимкнення, ребут, керування заздалегідь визначеними Docker-контейнерами та
жива телеметрія (CPU / RAM / SWAP / GPU).

Весь код — **Python** та **bash**. Без SSH, без виконання довільних команд.
Деталі — у [`docs/SPEC.md`](docs/SPEC.md) та [`docs/PLAN.md`](docs/PLAN.md).

![Веб-панель](docs/images/dashboard.png)

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
# редагуйте .env: API_TOKEN, AGENT_TOKEN, AGENT_* та BUILD_CONTEXT —
# шлях до кореня репозиторію (каталог, де лежать main/, common/ та
# requirements.txt); найбезпечніше — абсолютний, наприклад /home/user/oscontroll
# токени — довільні випадкові рядки, наприклад: openssl rand -hex 32
docker compose up -d
# веб-панель: https://<main-host>:8443  (токен — API_TOKEN)
```

### 2. Agent (кожен сервер)

```bash
cp deploy/agent/docker-compose.yml .
cp deploy/agent/.env.example .env
# скопіюйте сертифікати з main:
mkdir -p certs && cp <main>/certs/cert.crt <main>/certs/cert.key certs/
# редагуйте .env: MAIN_HOST, AGENT_NAME, AGENT_TOKEN, CONTAINERS, DOCKER_SOCK
# та BUILD_CONTEXT (шлях до кореня репозиторію, див. вище)
docker compose up -d
```

Примітка: `hostcmd.sh` (фіксований диспетчер команд хоста) копіюється в образ
при збірці (`agent/Dockerfile` → `/opt/tinyos/hostcmd.sh`). На хості нічого
встановлювати не треба — `HOSTCMD` у `docker-compose.yml` — це шлях
всередині контейнера.

На хості має працювати systemd: compose монтує `/run/systemd/private` та
маркер `/run/systemd/system`, щоб `systemctl` у контейнері керував PID 1
хоста напряму (poweroff / reboot). Якщо `systemctl` не може дістатися до
systemd хоста (наприклад, під Snap Docker, де bind-монт `/run/systemd/private`
не є живим сокетом хоста), `hostcmd.sh` переходить на fallback через
системний виклик `reboot(2)`, для якого потрібен `CAP_SYS_BOOT` (вже додано в
compose).

**Діагностика poweroff/reboot:** `docker logs tinyos-agent` показує стартові
діагностичні дані (змінні середовища, вміст `/run/systemd`, self-test
`systemctl` та наявність `CAP_SYS_BOOT`) та кожний запит із результатом;
`./logs/hostcmd.log` на хості містить точний код виходу та вивід і спроби
`systemctl`, і fallback `reboot(2)`. `reboot(2) failed: errno=1` (EPERM)
означає, що немає `CAP_SYS_BOOT`. Після змін у `agent/` перезбудуйте:
`docker compose up -d --build`.

Можна також просто клонувати репозиторій на обидві машини та запускати
`docker compose up -d` з `<repo>/deploy/main` (або `<repo>/deploy/agent`) —
тоді за замовчуванням `BUILD_CONTEXT=../..` вкаже на корінь репозиторію.

### Snap Docker

Snap Docker ізолює мережу та змінює шлях сокета:

- В `.env` agent: `DOCKER_SOCK=/var/snap/docker/current/docker.sock`.
- Для WoL: `NETWORK_MODE=host` (Snap Docker підтримує host-мережу). Якщо
  broadcast не доходить до LAN, перевірте мережеві налаштування snap.
- Poweroff/reboot: під Snap Docker bind-монт `/run/systemd/private` не є
  живим сокетом хоста, тому `systemctl` падає, а `hostcmd.sh` використовує
  fallback `reboot(2)` (`CAP_SYS_BOOT`, вже в compose). Це жорстке
  вимкнення/ребут (без зупинки сервісів systemd).

### AMD GPU-телеметрія (опційно)

`hostcmd.sh` працює всередині контейнера, тому для GPU-телеметрії контейнеру
потрібні `amd-smi` та пристрої GPU. На хості з AMD GPU:

1. Встановіть `amd-smi` на хості (напр., Ubuntu 24.04+: `sudo apt install amd-smi`).
2. Запустіть агента з GPU-override:
   ```
   docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
   ```
   Override монтує бінарник `amd-smi` з хоста та `/dev/kfd` + `/dev/dri`
   в контейнер.
3. **Не** використовуйте override на хостах без AMD GPU — контейнер не
   запуститься, бо там немає `/dev/kfd`.

`hostcmd.sh` шукає `amd-smi` через змінну `AMDSMI`, змонтований
`/opt/tinyos/amd-smi` або PATH контейнера; `docker logs tinyos-agent`
показує, який варіант знайдено при старті. Без `amd-smi` поле `amd_smi`
просто порожнє (це не помилка).

## Функції

- **Wake-on-LAN** по MAC (надсилає main).
- **Вимкнення** / **ребут** сервера.
- **Контейнери**: стан, start / stop / restart (білий список у `.env` agent).
- **Телеметрія** (раз на секунду): `amd-smi monitor`, температури CPU,
  RAM, SWAP, load, uptime.

## Home Assistant

У репозиторії є кастомна інтеграція `custom_components/oscontroll/`:
агенти, телеметрія, метрики GPU та керування в Home Assistant.

Встановлення та налаштування:
[docs/HOME_ASSISTANT.uk.md](docs/HOME_ASSISTANT.uk.md).

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
docs/      # SPEC.md, PLAN.md, HOME_ASSISTANT.md/.uk.md, images/
custom_components/  # інтеграція Home Assistant (oscontroll)
```
