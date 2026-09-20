#!/usr/bin/env bash
# OSControl — target-server installer.
#
# Installs the OSControl daemons (agent, executor, docker-proxy) from this
# bundle as systemd services. The bundle is produced by the build container
# on the control server (docker volume "osagent-build") and copied here.
#
# Host requirements (all standard on Ubuntu 22.04+, nothing extra installed):
#   bash, systemd, python3 (3.8+, stdlib only), docker (Docker Engine),
#   coreutils, sudo, openssl (optional, for key verification).
#
# Usage (as root on the TARGET server, from the bundle directory):
#   sudo bash install.sh --controller-url wss://192.168.1.20:9443 \
#                        --containers nginx,postgres \
#                        [--telemetry-interval 1] [--prefix /opt/osagent]
#   sudo bash install.sh --uninstall
set -euo pipefail

PREFIX=/opt/osagent
CONTROLLER_URL=""
CONTAINERS=""
INTERVAL=1
UNINSTALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --controller-url) CONTROLLER_URL="$2"; shift 2;;
    --containers) CONTAINERS="$2"; shift 2;;
    --telemetry-interval) INTERVAL="$2"; shift 2;;
    --prefix) PREFIX="$2"; shift 2;;
    --uninstall) UNINSTALL=1; shift;;
    *) echo "unknown argument: $1" >&2; exit 1;;
  esac
done

BUNDLE="$(cd "$(dirname "$0")" && pwd)"
UNITS="osagent-agent osagent-executor osagent-docker-proxy"

if [ "$UNINSTALL" = 1 ]; then
  for u in $UNITS; do
    systemctl disable --now "$u" 2>/dev/null || true
    rm -f "/etc/systemd/system/$u.service"
  done
  rm -f /etc/sudoers.d/osagent
  rm -rf "$PREFIX" /etc/osagent
  userdel osagent 2>/dev/null || true
  systemctl daemon-reload
  echo "OSControl uninstalled."
  exit 0
fi

[ "$(id -u)" = 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
[ -n "$CONTROLLER_URL" ] || { echo "--controller-url is required (e.g. wss://192.168.1.20:9443)" >&2; exit 1; }
[ -n "$CONTAINERS" ] || { echo "--containers is required (comma-separated, e.g. nginx,postgres)" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || { echo "python3 not found (Ubuntu: apt install python3-minimal)" >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
  || { echo "python3 >= 3.8 required (found $(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))'))" >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo "systemd (systemctl) not found" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "docker not found — the docker proxy needs the Docker Engine" >&2; exit 1; }

for f in keys/ca.crt keys/agent.crt keys/agent.key \
         daemons/osagent_agent.py daemons/osagent_executor.py \
         daemons/osagent_docker_proxy.py daemons/osagent_common.py daemons/wslib.py \
         target/osagent-agent.service target/osagent-executor.service \
         target/osagent-docker-proxy.service target/sudoers.d-osagent; do
  [ -f "$BUNDLE/$f" ] || { echo "bundle is incomplete: missing $f" >&2; exit 1; }
done

echo "==> bundle integrity"
if [ -f "$BUNDLE/MANIFEST" ]; then
  ( cd "$BUNDLE" && sha256sum -c MANIFEST >/dev/null ) \
    || { echo "bundle integrity check failed (MANIFEST mismatch)" >&2; exit 1; }
  if command -v openssl >/dev/null 2>&1; then
    ( cd "$BUNDLE" && openssl verify -CAfile keys/ca.crt keys/agent.crt >/dev/null ) \
      || { echo "agent certificate does not verify against the bundle CA" >&2; exit 1; }
  fi
else
  echo "    (no MANIFEST — skipping integrity check)"
fi

echo "==> system user osagent (uid 10001)"
id -u osagent >/dev/null 2>&1 \
  || useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin osagent

echo "==> daemons -> $PREFIX/daemons"
install -d -m 0755 "$PREFIX/daemons"
cp -f "$BUNDLE/daemons/"*.py "$PREFIX/daemons/"
install -d -m 0755 "$PREFIX/daemons/web"
cp -f "$BUNDLE/daemons/web/"* "$PREFIX/daemons/web/"
chown -R root:root "$PREFIX/daemons"
chmod -R a+rX "$PREFIX/daemons"

echo "==> certificates -> /etc/osagent/certs"
install -d -m 0750 -o osagent -g osagent /etc/osagent
install -d -m 0750 -o osagent -g osagent /etc/osagent/certs
install -m 0644 "$BUNDLE/keys/ca.crt" /etc/osagent/certs/ca.crt
install -m 0644 "$BUNDLE/keys/agent.crt" /etc/osagent/certs/agent.crt
install -m 0600 -o osagent -g osagent "$BUNDLE/keys/agent.key" /etc/osagent/certs/agent.key

echo "==> config -> /etc/osagent/agent.json"
OA_CONTROLLER_URL="$CONTROLLER_URL" OA_CONTAINERS="$CONTAINERS" OA_INTERVAL="$INTERVAL" \
python3 - /etc/osagent/agent.json <<'PY'
import json, os, sys
cfg = {
    "controller": {"url": os.environ["OA_CONTROLLER_URL"]},
    "executor": {"socket": "/run/osagent/executor.sock"},
    "docker": {
        "endpoint": "unix:///run/osagent/docker.sock",
        "containers": [c.strip() for c in os.environ["OA_CONTAINERS"].split(",") if c.strip()],
    },
    "telemetry": {"interval": float(os.environ.get("OA_INTERVAL", "1"))},
    "tls": {
        "ca": "/etc/osagent/certs/ca.crt",
        "cert": "/etc/osagent/certs/agent.crt",
        "key": "/etc/osagent/certs/agent.key",
    },
}
with open(sys.argv[1], "w") as f:
    json.dump(cfg, f, indent=2)
PY
chown osagent:osagent /etc/osagent/agent.json
chmod 600 /etc/osagent/agent.json

echo "==> sudo allowlist -> /etc/sudoers.d/osagent"
install -m 0440 "$BUNDLE/target/sudoers.d-osagent" /etc/sudoers.d/osagent
visudo -cf /etc/sudoers.d/osagent

echo "==> systemd units"
for u in $UNITS; do
  install -m 0644 "$BUNDLE/target/$u.service" "/etc/systemd/system/$u.service"
done
systemctl daemon-reload

echo "==> starting services"
systemctl enable --now osagent-executor
systemctl enable --now osagent-docker-proxy
systemctl enable --now osagent-agent
sleep 2
FAILED=0
for u in $UNITS; do
  if systemctl is-active --quiet "$u"; then
    echo "    $u: active"
  else
    echo "    $u: FAILED — check 'journalctl -u $u'" >&2
    FAILED=1
  fi
done
[ "$FAILED" = 0 ] || exit 1

echo "OK: OSControl installed on the target."
echo "    agent -> $CONTROLLER_URL"
echo "    containers: $CONTAINERS"
echo "    panel: https://<control-host>:8443 (token: build output / BUNDLE_INFO.txt)"
