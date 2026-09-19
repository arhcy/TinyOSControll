#!/usr/bin/env bash
# Run on the CONTROL server.
# Usage: install-controller.sh --wol-mac AA:BB:CC:DD:EE:FF [--wol-ip 192.168.1.10] [--api-token ...] [--web-hostname ctrl] [--web-ip 192.168.1.20]
set -euo pipefail
WOL_MAC=""; WOL_IP=""; API_TOKEN=""; WEB_HOST="localhost"; WEB_IP="127.0.0.1"
while [ $# -gt 0 ]; do
  case "$1" in
    --wol-mac) WOL_MAC="$2"; shift 2;;
    --wol-ip) WOL_IP="$2"; shift 2;;
    --api-token) API_TOKEN="$2"; shift 2;;
    --web-hostname) WEB_HOST="$2"; shift 2;;
    --web-ip) WEB_IP="$2"; shift 2;;
    *) echo "unknown arg $1" >&2; exit 1;;
  esac
done
[ -n "$WOL_MAC" ] || { echo "--wol-mac required" >&2; exit 1; }
[ -n "$API_TOKEN" ] || API_TOKEN="$(openssl rand -hex 24)"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p deploy/controller/config deploy/controller/certs
if [ ! -f deploy/controller/certs/ca.crt ]; then
  bash "$REPO/deploy/scripts/gen-certs.sh" deploy/controller/certs "$WEB_HOST" "$WEB_IP"
fi
echo "API token: $API_TOKEN"

{
  echo "listen:"
  echo "  web: ":8443""
  echo "  management: ":9443""
  echo "api_token: "$API_TOKEN""
  echo "wol:"
  echo "  mac: "$WOL_MAC""
  echo "  ip: "$WOL_IP""
  echo "  port: 9"
  echo "telemetry:"
  echo "  history_minutes: 60"
  echo "tls:"
  echo "  ca: /etc/osagent/certs/ca.crt"
  echo "  cert: /etc/osagent/certs/controller.crt"
  echo "  key: /etc/osagent/certs/controller.key"
} > deploy/controller/config/controller.yaml

docker build -f deploy/Dockerfile.controller -t osagent-controller:local .
docker compose -f deploy/controller/docker-compose.yml up -d
echo "OK: controller installed. Panel: https://$WEB_HOST:8443"
