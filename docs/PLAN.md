# TinyOSControll — план виконання та тестування

## 1. План реалізації

| # | Етап | Зміст | Статус |
|---|---|---|---|
| 1 | Спільний фундамент | `common/protocol.py` (типи повідомлень, encode/decode), `common/tlsutil.py` (mTLS-контексти), `common/wol.py` (магічний пакет) | ✅ |
| 2 | Agent | `agent/agent.py` (mTLS-WS-клієнт, обробники дій, цикл телеметрії), `agent/hostcmd.sh` (bash-диспетчер команд), `agent/entrypoint.sh`, `agent/Dockerfile` | ✅ |
| 3 | Main | `main/main.py` (mTLS-WS-сервер, реєстр агентів, request/response, store телеметрії, веб-API + SSE, аудит, WoL), `main/web/`, `main/Dockerfile` | ✅ |
| 4 | Розгортання | `deploy/main/docker-compose.yml` + `.env.example`, `deploy/agent/docker-compose.yml` + `.env.example`, `tools/gen-certs.sh` | ✅ |
| 5 | Верифікація | `bash -n` для всіх `.sh`; `python -m py_compile` для всіх `.py`; модульні тести (venv); локальна інтеграція main+agent | ✅ |

> Встановлення та тестування на реальних серверах **не входить** до плану
> розробки (за вимогою). Локальне тестування — у python-venv.

## 2. Структура репозиторію

```
common/                       # спільний Python-код (protocol, tls, wol)
  protocol.py  tlsutil.py  wol.py
agent/                        # контейнер agent
  agent.py  hostcmd.sh  entrypoint.sh  Dockerfile
main/                         # контейнер main
  main.py  web/{index.html,app.js,style.css}  Dockerfile
deploy/
  main/{docker-compose.yml,.env.example}
  agent/{docker-compose.yml,.env.example}
tools/gen-certs.sh            # генерація self-signed сертифіката
tests/                        # модульні + локальна інтеграція
docs/{SPEC.md,PLAN.md}
```

## 3. План тестування

### 3.1. Модульні (автоматичні, python venv, `python -m pytest` або `unittest`)

| Модуль | Що перевіряється |
|---|---|
| `protocol` | encode/decode всіх типів повідомлень; валідація; помилки на некоректному JSON |
| `wol` | структура магічного пакета (6×FF + 16×MAC); валідні/невалідні MAC |
| `tlsutil` | побудова server/client-контекстів; відсутність файлів → помилка |
| `agent` (hostcmd) | фільтрація контейнерів за білим списком; відмова невідомій дії; парсинг meminfo/thermal |
| `main` | rate-limiter; авторизація (токен, константний час); реєстр агентів (online/offline); store телеметрії |

### 3.2. Локальна інтеграція (venv, без реальних серверів)

1. `tools/gen-certs.sh ./certs localhost` — сертифікат.
2. Запустити `main` (локально, на 127.0.0.1) та `agent` (локально,
   `AGENT_NAME=alpha`, `MAIN_HOST=127.0.0.1`).
3. Agent підключається, `hello` приймається, статус «онлайн».
4. Телеметрія надходить (RAM/SWAP/load; CPU/GPU — порожні на хості без
   thermal zones / GPU — це очікувано).
5. `health` → `ok`. `containers.list` → список (на хості без docker — помилка
   очікувана, перевіряється формат відповіді).
6. Негативні: з'єднання без клієнтського сертифіката відхиляється;
   неправильний токен → `hello_err`; невідомий agent → `hello_err`.
7. Аудит: у логах main — дії з agent та результатом.

### 3.3. Приймальний чек-лист (локально)

- [x] `bash -n` для всіх `.sh` — чисто
- [x] `python -m py_compile` для всіх `.py` — чисто
- [x] Модульні тести проходять
- [x] Agent→main mTLS-з'єднання встановлюється локально
- [x] `hello` з правильним токеном → `hello_ok`; неправильний → `hello_err`
- [x] Телеметрія надходить кожну секунду
- [x] Аудит-лог заповнюється

## 4. Журнал верифікації

- 2026-09-21: `bash -n` для `tools/gen-certs.sh`, `agent/entrypoint.sh`, `agent/hostcmd.sh` — чисто.
- 2026-09-21: `python -m py_compile` для всіх `.py` (common, agent, main, tests) — чисто.
- 2026-09-21: `python -m pytest` — **20 passed** (19 модульних `common` + 1 локальна інтеграція main+agent).
- 2026-09-21: локальна інтеграція (venv, `tests/test_integration.py`): mTLS-з'єднання agent→main; `hello`→`hello_ok` (неправильний токен → `hello_err`); телеметрія; `health`/`containers.list` через `forward`; web-API (list/containers/poweroff/wake) + SSE; whitelist-accept/reject; `/` → SPA; `/ws` недоступний на web-порту; відмова mTLS без клієнтського сертифіката. WoL-відправлення в тесті застубовано (offline-safe).
- 2026-09-21: виправлено `agent/Dockerfile` — додано пакет `systemd` (постачає `systemctl` для `poweroff`/`reboot` через змонтований `/run/systemd/private`).
