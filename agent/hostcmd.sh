#!/usr/bin/env bash
# hostcmd.sh — fixed dispatcher for TinyOSControll agent host operations.
#
# Only the commands below are recognized. There is NO arbitrary command
# execution: every branch is explicit, and user-supplied values are validated
# before use. This is the single place that touches host system commands.
set -euo pipefail

LOG_FILE="${HOSTCMD_LOG:-/var/log/tinyos/hostcmd.log}"

log() {
  local line="[$(date -u +%FT%TZ)] $*"
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
  echo "$line" >> "$LOG_FILE" 2>/dev/null || echo "$line"
}

cmd="${1:-}"
shift || true

is_container_name() { [[ "${1:-}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; }

# Fallback for poweroff/reboot when systemctl cannot reach host systemd
# (notably Snap Docker, where the /run/systemd/private bind mount is not the
# host's live socket and connect() returns EHOSTDOWN). Asks the kernel
# directly via the reboot(2) syscall; requires CAP_SYS_BOOT (see
# deploy/agent/docker-compose.yml). Note: this is a hard power-off/reboot and
# does not run systemd's clean service shutdown.
# $1 = hex command: 0x4321fedc (RB_POWER_OFF) or 0x01234567 (RB_AUTOBOOT)
_reboot_syscall() {
  python3 - "$1" <<'PY'
import ctypes, sys
try:
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
except OSError:
    libc = ctypes.CDLL(None, use_errno=True)
libc.reboot.restype = ctypes.c_int
rc = libc.reboot(int(sys.argv[1], 16))
if rc != 0:
    sys.stderr.write("reboot(2) failed: errno=%d\n" % ctypes.get_errno())
    sys.exit(1)
PY
}

case "$cmd" in
  health)
    uptime_s="$(cut -d' ' -f1 /proc/uptime 2>/dev/null || echo 0)"
    printf '{"uptime_seconds":%s}\n' "$uptime_s"
    ;;

  poweroff)
    log "poweroff: trying systemctl poweroff"
    if out="$(systemctl poweroff 2>&1)"; then
      log "poweroff: ok (systemctl)"
    else
      rc=$?
      log "poweroff: systemctl FAILED rc=$rc: $out — trying reboot(2)"
      if out2="$(_reboot_syscall 0x4321fedc 2>&1)"; then
        log "poweroff: ok (reboot(2))"
      else
        rc2=$?
        log "poweroff: reboot(2) FAILED rc=$rc2: $out2"
        echo "poweroff failed: systemctl rc=$rc; reboot(2) rc=$rc2: $out2" >&2
        exit "$rc2"
      fi
    fi
    ;;

  reboot)
    log "reboot: trying systemctl reboot"
    if out="$(systemctl reboot 2>&1)"; then
      log "reboot: ok (systemctl)"
    else
      rc=$?
      log "reboot: systemctl FAILED rc=$rc: $out — trying reboot(2)"
      if out2="$(_reboot_syscall 0x01234567 2>&1)"; then
        log "reboot: ok (reboot(2))"
      else
        rc2=$?
        log "reboot: reboot(2) FAILED rc=$rc2: $out2"
        echo "reboot failed: systemctl rc=$rc; reboot(2) rc=$rc2: $out2" >&2
        exit "$rc2"
      fi
    fi
    ;;

  containers.list)
    # $1 = comma-separated whitelist of container names
    python3 - "${1:-}" <<'PY'
import json, sys, subprocess
names = [n for n in sys.argv[1].split(",") if n]
out = {}
for n in names:
    try:
        st = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", n],
                            capture_output=True, text=True, timeout=10)
        state = st.stdout.strip() or "missing"
    except Exception:
        state = "missing"
    out[n] = {"state": state}
print(json.dumps(out))
PY
    ;;

  containers.action)
    name="${1:-}"
    action="${2:-}"
    case "$action" in start|stop|restart) ;; *) echo "invalid action" >&2; exit 2 ;; esac
    is_container_name "$name" || { echo "invalid container name" >&2; exit 2; }
    log "containers.action $name $action"
    docker "$action" "$name"
    printf '{"ok":true}\n'
    ;;

  telemetry)
    python3 - <<'PY'
import glob, json, subprocess

def read_meminfo():
    d = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, rest = line.partition(":")
                parts = rest.split()
                if parts:
                    d[k.strip()] = int(parts[0])
    except Exception:
        pass
    return d

def mb(kb):
    return round(kb / 1024.0, 1)

def pct(used, total):
    return round(used * 100.0 / total, 1) if total else 0.0

mi = read_meminfo()
ram_total = mi.get("MemTotal", 0)
ram_avail = mi.get("MemAvailable", mi.get("MemFree", 0))
ram_used = max(0, ram_total - ram_avail)
swap_total = mi.get("SwapTotal", 0)
swap_free = mi.get("SwapFree", 0)
swap_used = max(0, swap_total - swap_free)

cpu_temp = None
candidates = (sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp"))
              + sorted(glob.glob("/sys/class/hwmon/hwmon*/temp*_input")))
for f in candidates:
    try:
        v = int(open(f).read().strip())
        cpu_temp = round(v / 1000.0, 1) if v > 1000 else float(v)
        break
    except Exception:
        continue

amd = None
try:
    r = subprocess.run(["amd-smi", "monitor"], capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        amd = r.stdout
except Exception:
    amd = None

print(json.dumps({
    "cpu_temp_c": cpu_temp,
    "ram": {"total_mb": mb(ram_total), "used_mb": mb(ram_used),
            "percent": pct(ram_used, ram_total)},
    "swap": {"total_mb": mb(swap_total), "used_mb": mb(swap_used),
             "percent": pct(swap_used, swap_total)},
    "amd_smi": amd,
}))
PY
    ;;

  *)
    echo "unknown command: ${cmd}" >&2
    exit 2
    ;;
esac
