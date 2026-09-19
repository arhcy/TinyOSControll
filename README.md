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

## Швидкий старт

1. Контрольний сервер (генерує CA та сертифікати):
   bash deploy/scripts/install-controller.sh --wol-mac AA:BB:CC:DD:EE:FF      --wol-ip 192.168.1.10 --web-hostname ctrl --web-ip 192.168.1.20
   Скрипт покаже API-токен — він потрібен у панелі.
2. Скопіюйте deploy/controller/certs/{ca.crt,agent.crt,agent.key}
   на таргет у deploy/target/certs/.
3. Цільовий сервер:
   bash deploy/scripts/install-target.sh --controller-url wss://192.168.1.20:9443      --containers nginx,postgres
4. Відкрийте https://<controller>:8443, введіть токен.

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
