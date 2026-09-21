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

case "$cmd" in
  health)
    uptime_s="$(cut -d' ' -f1 /proc/uptime 2>/dev/null || echo 0)"
    printf '{"uptime_seconds":%s}\n' "$uptime_s"
    ;;

  poweroff)
    log "poweroff"
    systemctl poweroff
    ;;

  reboot)
    log "reboot"
    systemctl reboot
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
