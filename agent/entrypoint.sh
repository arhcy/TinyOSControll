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
# CAP_SYS_BOOT (bit 19) is required by the reboot(2) poweroff/reboot fallback
# in hostcmd.sh. Report it so a missing cap_add is visible at startup.
cap_eff="$(awk '/^CapEff:/{print $2}' /proc/self/status 2>/dev/null || true)"
if [ -n "$cap_eff" ] && [ $(( 0x"$cap_eff" & 0x80000 )) -ne 0 ]; then
  echo "[$(ts)] entrypoint: CAP_SYS_BOOT present (reboot(2) fallback available)"
else
  echo "[$(ts)] entrypoint: CAP_SYS_BOOT MISSING (reboot(2) fallback will fail; add cap_add: SYS_BOOT)"
fi

exec python3 /opt/tinyos/agent.py
