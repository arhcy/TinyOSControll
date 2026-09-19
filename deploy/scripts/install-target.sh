#!/usr/bin/env bash
# Run on the TARGET server.
# Usage: install-target.sh --controller-url wss://192.168.1.20:9443 --containers nginx,postgres [--telemetry-interval 1s]
set -euo pipefail
CONTROLLER_URL=""; CONTAINERS=""; INTERVAL="1s"
while [ $# -gt 0 ]; do
  case "$1" in
    --controller-url) CONTROLLER_URL="$2"; shift 2;;
    --containers) CONTAINERS="$2"; shift 2;;
    --telemetry-interval) INTERVAL="$2"; shift 2;;
    *) echo "unknown arg $1" >&2; exit 1;;
  esac
done
[ -n "$CONTROLLER_URL" ] || { echo "--controller-url required" >&2; exit 1; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_UID=10001

id -u osagent &>/dev/null || useradd --system --uid "$AGENT_UID" --no-create-home --shell /usr/sbin/nologin osagent
install -m 0440 "$REPO/deploy/target/sudoers.d-osagent" /etc/sudoers.d/osagent
visudo -cf /etc/sudoers.d/osagent

if [ ! -x dist/osagent-executor ]; then
  GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o dist/osagent-executor ./cmd/osagent-executor
fi
install -m 0755 dist/osagent-executor /usr/local/bin/osagent-executor
install -m 0644 "$REPO/deploy/target/osagent-executor.service" /etc/systemd/system/osagent-executor.service
systemctl daemon-reload
systemctl enable --now osagent-executor

mkdir -p deploy/target/config deploy/target/certs
[ -f deploy/target/certs/ca.crt ] || { echo "put certs into deploy/target/certs (ca.crt agent.crt agent.key)" >&2; exit 1; }

IFS=',' read -ra CSLIST <<< "$CONTAINERS"
{
  echo "controller:"
  echo "  url: "$CONTROLLER_URL""
  echo "executor:"
  echo "  socket: /run/osagent/executor.sock"
  echo "docker:"
  echo "  endpoint: unix:///var/run/docker-proxy/docker.sock"
  echo "  containers:"
  for c in "${CSLIST[@]}"; do echo "    - $c"; done
  echo "telemetry:"
  echo "  interval: $INTERVAL"
  echo "tls:"
  echo "  ca: /etc/osagent/certs/ca.crt"
  echo "  cert: /etc/osagent/certs/agent.crt"
  echo "  key: /etc/osagent/certs/agent.key"
} > deploy/target/config/agent.yaml

docker compose -f deploy/target/docker-compose.yml up -d --build
echo "OK: target installed"
