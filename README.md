# TinyOSControll

**Languages:** [English](README.md) | [Українська](README.uk.md)

A network server management tool: a web panel on the central machine
(**main**) controls several remote servers (**agent**) — Wake-on-LAN,
shutdown, reboot, management of pre-defined Docker containers and live
telemetry (CPU / RAM / SWAP / GPU).

All code is **Python** and **bash**. No SSH, no arbitrary command execution.
Details in [`docs/SPEC.md`](docs/SPEC.md) and [`docs/PLAN.md`](docs/PLAN.md).

## Architecture

- **main** — container: web interface (HTTPS) + mTLS-WS server that talks to
  the agents + sends WoL.
- **agent** — container (several on different servers): one daemon + a
  bash dispatcher of system commands. Initiates the outbound mTLS connection
  to main.

The connection is an **mTLS-WebSocket** (shared self-signed certificate),
TLS ≥ 1.2. The agent opens no inbound ports.

## Installation

### 0. Certificate generation (once, on main)

```bash
tools/gen-certs.sh ./certs <MAIN_HOST>
# for example:
tools/gen-certs.sh ./certs 192.168.1.20
```

Creates `certs/cert.key` + `certs/cert.crt`.

### 1. Main

```bash
# copy deploy/main/docker-compose.yml and .env.example into the working directory
cp deploy/main/docker-compose.yml .
cp deploy/main/.env.example .env
# edit .env: API_TOKEN, AGENT_TOKEN, AGENT_* and BUILD_CONTEXT —
# the path to the repository root (the directory with main/, common/ and
# requirements.txt); an absolute path is safest, e.g. /home/user/oscontroll
# tokens can be any random string, e.g.: openssl rand -hex 32
docker compose up -d
# web panel: https://<main-host>:8443  (token — API_TOKEN)
```

### 2. Agent (each server)

```bash
cp deploy/agent/docker-compose.yml .
cp deploy/agent/.env.example .env
# copy the certificates from main:
mkdir -p certs && cp <main>/certs/cert.crt <main>/certs/cert.key certs/
# edit .env: MAIN_HOST, AGENT_NAME, AGENT_TOKEN, CONTAINERS, DOCKER_SOCK and
# BUILD_CONTEXT (path to the repository root, see above)
docker compose up -d
```

You can also simply clone the repository onto both machines and run
`docker compose up -d` from `<repo>/deploy/main` (or `<repo>/deploy/agent`) —
the default `BUILD_CONTEXT=../..` then resolves to the repository root.

### Snap Docker

Snap Docker isolates the network and changes the socket path:

- In the agent `.env`: `DOCKER_SOCK=/var/snap/docker/current/docker.sock`.
- For WoL: `NETWORK_MODE=host` (Snap Docker supports the host network). If the
  broadcast does not reach the LAN, check the snap network settings.

## Features

- **Wake-on-LAN** by MAC (sent by main).
- **Shutdown** / **reboot** of the server.
- **Containers**: status, start / stop / restart (allow-list in the agent `.env`).
- **Telemetry** (once per second): `amd-smi monitor`, CPU temperatures,
  RAM, SWAP, load, uptime.

## Local testing (without real servers)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q
```

See `docs/PLAN.md` section 3.2 for the local integration scenario.

## Structure

```
common/    # protocol, tls, wol (shared code)
agent/     # agent.py, hostcmd.sh, entrypoint.sh, Dockerfile
main/      # main.py, web/, Dockerfile
deploy/    # docker-compose.yml + .env.example for main and agent
tools/     # gen-certs.sh
tests/     # unit + local integration
docs/      # SPEC.md, PLAN.md
```
