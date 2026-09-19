# OS Control — план виконання та тестування

## 1. План реалізації

| # | Етап | Зміст | Статус |
|---|---|---|---|
| 1 | Спільний фундамент | `go.mod`, `internal/protocol` (типи повідомлень), `internal/config` (YAML + валідація), `internal/tlsutil` (mTLS) | ✅ |
| 2 | WoL | `internal/wol`: парсинг MAC, магічний пакет, broadcast/directed відправка | ✅ |
| 3 | Executor | `internal/executor`: JSON-lines протокол, unix-сокет, перевірка `SO_PEERCRED`, таблиця команд (`sysinfo`, `amdsmi`, `poweroff`), парсери sysfs/proc | ✅ |
| 4 | Docker-клієнт | `internal/dockerapi`: мінімальний HTTP-клієнт Docker API (unix/tcp), list + start/stop/restart | ✅ |
| 5 | Агент | `internal/agent`: mTLS WS-клієнт з reconnect/backoff, обробники дій, цикл телеметрії, білий список контейнерів, парсинг amd-smi | ✅ |
| 6 | Контролер | `internal/controller`: WS-сервер (mTLS), agent-client (request/response, online-статус), SSE-hub, store телеметрії, веб-API, rate-limit, аудит, WoL | ✅ |
| 7 | Веб-панель | `web/`: index.html + app.js + style.css (embed), live-оновлення через SSE, підтвердження небезпечних дій | ✅ |
| 8 | Розгортання | Dockerfile (agent, controller), docker-compose (control/target), systemd-юніт executor, sudoers, скрипти gen-certs / install | ✅ |
| 9 | Верифікація | `go vet`, `go test`, cross-compile linux (amd64/arm64), gofmt | ✅ |

## 2. Структура репозиторію

```
cmd/osagent-{controller,agent,executor}/   # бинарі
internal/{protocol,config,tlsutil,wol,executor,dockerapi,telemetry,controller,agent}/
web/                                        # SPA (embed)
deploy/                                     # Dockerfile, compose, systemd, sudoers, scripts
docs/                                       # SPEC.md, PLAN.md
```

## 3. План тестування

### 3.1. Модульні (автоматичні, `go test ./...`)

| Модуль | Що перевіряється |
|---|---|
| `wol` | довжина/структура магічного пакета (6×FF + 16×MAC), валідні/невалідні MAC |
| `protocol` | marshal/unmarshal повідомлень, payload-типи |
| `config` | валідація: MAC, URL (wss://), інтервали, порожні поля, відсутній файл |
| `executor` | парсинг meminfo/thermal/loadavg/uptime (з temp-каталогу), дозволи команд, відмова невідомій команді; `SO_PEERCRED`-перевірка (лише linux) |
| `dockerapi` | list/action проти мок-сервера на unix-сокеті; 304/409 → ок; 404 → помилка |
| `agent` | фільтрація контейнерів за білим списком, парсинг amd-smi (наприсутність/відсутність полів) |
| `controller` | rate-limiter, авторизація (токен, константний час), SSE-hub (публікація/підписка) |

### 3.2. Інтеграційні (на Ubuntu + Docker, вручну/скриптом)

1. `gen-certs.sh` → сертифікати; `install-controller.sh` / `install-target.sh`.
2. `docker compose ps` на обох хостах — усі контейнери up.
3. `journalctl -u osagent-executor` — сокет створено.
4. Веб-панель: https://<controller>:8443 — токен, статус агента «онлайн».
5. Телеметрія: температури CPU/RAM/GPU оновлюються кожну секунду; блок amd-smi
   збігається з виводом `sudo amd-smi monitor` на таргеті.
6. Контейнери: список = білий список; start/stop/restart працює,
   `docker ps` на таргеті підтверджує зміну стану.
7. Shutdown: кнопка з підтвердженням → таргет вимикається, панель показує офлайн.
8. WoL: після вимкнення — WoL → машина завантажується, агент повертається онлайн.
9. Негативні: з'єднання без клієнтського сертифіката відхиляється;
   запит до контейнера поза білим списком → помилка; хтось із іншого uid
   не може підключитись до executor-сокету.
10. Аудит: у логах контролера — усі дії з IP та результатом.

### 3.3. Приймальний чек-лист

- [ ] Панель відкривається за HTTPS, токен працює, без токена — 401
- [ ] Статус агента змінюється онлайн/офлайн при вимкненні/запуску
- [ ] WoL прокидає вимкнену машину
- [ ] Shutdown вимикає машину
- [ ] Стани контейнерів актуальні; start/stop/restart працюють
- [ ] Телеметрія (CPU, RAM, GPU) оновлюється в реальному часі
- [ ] Таргет не має вхідних портів (`ss -tlnp` — лише локальні сокети)
- [ ] sudoers містить лише дві команди; `sudo -l -U osagent` це підтверджує

## 4. Журнал верифікації

- 2026-09-19: go build, go vet, go test -count=1 — усі тести проходять; gofmt — чисто;
  cross-compile linux/amd64 та linux/arm64 — успішно. Бинарі для розгортання у dist/ (linux/amd64).
- Виправлено: API nhooyr.io/websocket v1.8.17 (Close, Accept) у internal/controller;
  httptest.Server.Start у internal/dockerapi/client_test.go;
  type-assertions до *net.UDPConn / *net.UnixConn у internal/wol/broadcast_linux.go
  та internal/executor/server.go.
- Інтеграційні тести (3.2/3.3) потребують двох Ubuntu-серверів — не виконано.
