#!/usr/bin/env bash
# Agent container entrypoint: make hostcmd executable, then run the daemon.
set -euo pipefail

ts() { date -u +%FT%TZ; }

echo "[$(ts)] entrypoint: starting tinyos agent"
echo "[$(ts)] entrypoint: HOSTCMD=${HOSTCMD:-<unset>} DBUS_SYSTEM_BUS_ADDRESS=${DBUS_SYSTEM_BUS_ADDRESS:-<unset>}"
echo "[$(ts)] entrypoint: /run/systemd contents:"
ls -la /run/systemd/ 2>&1 | sed 's/^/    /' || true
if out="$(systemctl is-system-running 2>&1)"; then rc=0; else rc=$?; fi
echo "[$(ts)] entrypoint: systemctl self-test rc=$rc: $out"

exec python3 /opt/tinyos/agent.py
