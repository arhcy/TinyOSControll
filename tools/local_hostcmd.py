"""Local, cross-platform hostcmd stub for testing TinyOSControll without
docker/systemd.

It mirrors the interface of agent/hostcmd.sh:

    hostcmd <cmd> [args...]

Commands:
    health
    poweroff
    reboot
    containers.list <comma-separated names>
    containers.action <name> <action>
    telemetry

Output is JSON on stdout. poweroff/reboot are no-ops (they only print ok) so
running the app locally never touches the host. Telemetry values fluctuate so
the web UI visibly updates each second.
"""

import json
import random
import sys
import time

_START = time.time()
_RAM_TOTAL_MB = 16384
_SWAP_TOTAL_MB = 4096


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "health":
        print(json.dumps({"uptime_seconds": round(time.time() - _START, 1)}))
    elif cmd in ("poweroff", "reboot"):
        # no-op in local mode: never touch the host
        print(json.dumps({"ok": True, "noop": True}))
    elif cmd == "containers.list":
        raw = sys.argv[2] if len(sys.argv) > 2 else ""
        names = [n for n in raw.split(",") if n]
        print(json.dumps({n: {"state": "running"} for n in names}))
    elif cmd == "containers.action":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        act = sys.argv[3] if len(sys.argv) > 3 else ""
        print(json.dumps({"ok": True, "container": name, "action": act, "noop": True}))
    elif cmd == "telemetry":
        used_mb = int(_RAM_TOTAL_MB * (0.30 + random.random() * 0.20))
        print(json.dumps({
            "cpu_temp_c": round(42 + random.random() * 10, 1),
            "ram": {"total_mb": _RAM_TOTAL_MB, "used_mb": used_mb,
                    "percent": round(used_mb / _RAM_TOTAL_MB * 100, 1)},
            "swap": {"total_mb": _SWAP_TOTAL_MB, "used_mb": 0, "percent": 0.0},
            "amd_smi": None,
        }))
    else:
        sys.stderr.write("unknown " + cmd)
        sys.exit(2)


if __name__ == "__main__":
    main()
