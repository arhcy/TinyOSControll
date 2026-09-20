#!/usr/bin/env bash
# OSControl build stage — runs INSIDE the build container.
#
# Produces the install bundle in /out (mounted docker volume "osagent-build"):
#   keys/        CA + controller + agent certificates (openssl, generated here)
#   daemons/     Python daemons (stdlib only), syntax-checked (the "build")
#   config/      controller.json (final) + agent.json (template for the target)
#   target/      systemd units + sudo allowlist for the target installer
#   install.sh   target-server installer (bash + coreutils only)
#   MANIFEST     sha256 checksums of the whole bundle
#   BUNDLE_INFO.txt  build parameters + API token
#
# Required env: WEB_HOSTNAME, WEB_IP, WOL_MAC
# Optional env: WOL_IP, API_TOKEN, CONTROLLER_URL, CONTAINERS, TELEMETRY_INTERVAL
set -euo pipefail

OUT=/out
SRC=/src

WEB_HOSTNAME="${WEB_HOSTNAME:?WEB_HOSTNAME is required (panel hostname, e.g. ctrl)}"
WEB_IP="${WEB_IP:?WEB_IP is required (control server IP, e.g. 192.168.1.20)}"
WOL_MAC="${WOL_MAC:?WOL_MAC is required (target MAC, e.g. AA:BB:CC:DD:EE:FF)}"
WOL_IP="${WOL_IP:-}"
API_TOKEN="${API_TOKEN:-}"
CONTROLLER_URL="${CONTROLLER_URL:-wss://$WEB_HOSTNAME:9443}"
CONTAINERS="${CONTAINERS:-}"
TELEMETRY_INTERVAL="${TELEMETRY_INTERVAL:-1}"

echo "==> cleaning $OUT"
find "$OUT" -mindepth 1 -delete
mkdir -p "$OUT/keys" "$OUT/daemons" "$OUT/config" "$OUT/target"

echo "==> generating TLS keys (CA + controller + agent)"
cd "$OUT/keys"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out ca.key 2>/dev/null
openssl req -new -x509 -key ca.key -sha256 -days 3650 -subj "/CN=OSAgent CA" -out ca.crt
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out controller.key 2>/dev/null
openssl req -new -key controller.key -subj "/CN=$WEB_HOSTNAME" -out controller.csr
printf 'subjectAltName=DNS:%s,DNS:localhost,IP:%s,IP:127.0.0.1\n' "$WEB_HOSTNAME" "$WEB_IP" > controller.ext
openssl x509 -req -in controller.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days 825 -sha256 -extfile controller.ext -out controller.crt 2>/dev/null
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out agent.key 2>/dev/null
openssl req -new -key agent.key -subj "/CN=osagent-agent" -out agent.csr
openssl x509 -req -in agent.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days 825 -sha256 -out agent.crt 2>/dev/null
rm -f *.csr *.ext *.srl
chmod 600 ca.key controller.key agent.key
chmod 644 ca.crt controller.crt agent.crt
# The controller container and the target "osagent" user both run as uid 10001.
chown 10001:10001 controller.crt controller.key agent.crt agent.key

echo "==> packaging daemons (Python, stdlib only)"
cp "$SRC/daemons/"*.py "$OUT/daemons/"
cp -r "$SRC/daemons/web" "$OUT/daemons/web"
chmod 644 "$OUT/daemons/"*.py
chmod -R a+rX "$OUT/daemons/web"

echo "==> build: syntax check"
python3 -m py_compile "$OUT/daemons/"*.py
rm -rf "$OUT/daemons/__pycache__"

echo "==> generating configs"
[ -n "$API_TOKEN" ] || API_TOKEN="$(openssl rand -hex 24)"
API_TOKEN="$API_TOKEN" WOL_MAC="$WOL_MAC" WOL_IP="$WOL_IP" \
CONTROLLER_URL="$CONTROLLER_URL" CONTAINERS="$CONTAINERS" \
TELEMETRY_INTERVAL="$TELEMETRY_INTERVAL" \
python3 - "$OUT" <<'PY'
import json, os, sys
out = sys.argv[1]
controller = {
    "listen": {"web": ":8443", "management": ":9443"},
    "api_token": os.environ["API_TOKEN"],
    "wol": {"mac": os.environ["WOL_MAC"], "ip": os.environ.get("WOL_IP", ""), "port": 9},
    "telemetry": {"history_minutes": 60},
    "tls": {"ca": "/out/keys/ca.crt",
            "cert": "/out/keys/controller.crt",
            "key": "/out/keys/controller.key"},
}
with open(os.path.join(out, "config", "controller.json"), "w") as f:
    json.dump(controller, f, indent=2)
agent = {
    "controller": {"url": os.environ["CONTROLLER_URL"]},
    "executor": {"socket": "/run/osagent/executor.sock"},
    "docker": {"endpoint": "unix:///run/osagent/docker.sock",
               "containers": [c for c in os.environ.get("CONTAINERS", "").split(",") if c]},
    "telemetry": {"interval": float(os.environ.get("TELEMETRY_INTERVAL", "1"))},
    "tls": {"ca": "/etc/osagent/certs/ca.crt",
            "cert": "/etc/osagent/certs/agent.crt",
            "key": "/etc/osagent/certs/agent.key"},
}
with open(os.path.join(out, "config", "agent.json"), "w") as f:
    json.dump(agent, f, indent=2)
PY
chown 10001:10001 "$OUT/config/controller.json" "$OUT/config/agent.json"
chmod 600 "$OUT/config/"*.json

echo "==> packaging target install parts"
cp "$SRC/units/"*.service "$OUT/target/"
cp "$SRC/sudoers.d-osagent" "$OUT/target/"
cp "$SRC/install.sh" "$OUT/install.sh"
chmod 755 "$OUT/install.sh"
chmod 644 "$OUT/target/"*

echo "==> bundle info + manifest"
cat > "$OUT/BUNDLE_INFO.txt" <<INFO
Generated:          $(date -u +%Y-%m-%dT%H:%M:%SZ)
WEB_HOSTNAME:       $WEB_HOSTNAME
WEB_IP:             $WEB_IP
WOL_MAC:            $WOL_MAC
WOL_IP:             $WOL_IP
CONTROLLER_URL:     $CONTROLLER_URL
CONTAINERS:         $CONTAINERS
TELEMETRY_INTERVAL: $TELEMETRY_INTERVAL
API_TOKEN:          $API_TOKEN
INFO
chmod 644 "$OUT/BUNDLE_INFO.txt"
( cd "$OUT" && find . -type f ! -name MANIFEST -print0 | sort -z | xargs -0 sha256sum > MANIFEST )

echo "==> bundle ready in $OUT (docker volume: osagent-build)"
echo "API token: $API_TOKEN"
