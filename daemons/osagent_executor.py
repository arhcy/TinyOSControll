#!/usr/bin/env python3
"""OSControl host executor (Target host, systemd, user osagent).

Executes a fixed allowlist of host commands over a unix socket (JSON lines)
and verifies the peer with SO_PEERCRED (kernel-checked uid). No shell, no
arbitrary commands. Standard library only.
"""
import argparse
import json
import os
import socket
import struct
import subprocess
import threading

import osagent_common as common

SO_PEERCRED = getattr(socket, "SO_PEERCRED", 17)

# Fixed allowlist: exact argv, no shell, no wildcards.
COMMANDS = {
    "amdsmi": (["/usr/bin/sudo", "/usr/bin/amd-smi", "monitor"], 10.0),
    "poweroff": (["/usr/bin/sudo", "/usr/bin/systemctl", "poweroff"], 15.0),
}


def collect_sysinfo():
    """Host telemetry from sysfs/proc (no sudo required)."""
    d = {"thermals": [], "hostname": socket.gethostname()}
    base = "/sys/class/thermal"
    try:
        for name in sorted(os.listdir(base)):
            if not name.startswith("thermal_zone"):
                continue
            zdir = os.path.join(base, name)
            if not os.path.isdir(zdir):
                continue
            try:
                with open(os.path.join(zdir, "temp")) as f:
                    milli = int(f.read().strip())
            except (OSError, ValueError):
                continue
            zone = {"temp_c": milli / 1000.0}
            try:
                with open(os.path.join(zdir, "type")) as f:
                    zone["type"] = f.read().strip()
            except OSError:
                pass
            d["thermals"].append(zone)
    except OSError:
        pass
    total = avail = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    if total > 0:
        used = max(total - avail, 0)
        d["ram"] = {"total_kb": total, "available_kb": avail, "used_kb": used,
                    "used_pct": used / total * 100.0}
    try:
        with open("/proc/loadavg") as f:
            l1, l5, l15 = f.read().split()[:3]
        d["load"] = {"l1": float(l1), "l5": float(l5), "l15": float(l15)}
    except (OSError, ValueError):
        pass
    try:
        with open("/proc/uptime") as f:
            d["uptime_sec"] = float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    return d


def run_command(argv, timeout):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = ""
        if isinstance(e.stdout, str):
            out += e.stdout
        if isinstance(e.stderr, str):
            out += e.stderr
        return out, "command timed out"
    except OSError as e:
        return "", str(e)
    out = p.stdout + p.stderr
    if p.returncode != 0:
        return out, "exit code %d" % p.returncode
    return out, None


def dispatch(req, log):
    cmd = req.get("cmd")
    if cmd == "sysinfo":
        return {"ok": True, "data": collect_sysinfo()}
    if cmd in COMMANDS:
        argv, timeout = COMMANDS[cmd]
        out, err = run_command(argv, timeout)
        if err:
            log.info("command %s failed: %s", cmd, err)
            return {"ok": False, "error": err}
        return {"ok": True, "data": {"raw": out}}
    return {"ok": False, "error": "unknown command"}


def handle(conn, allow_uid, log):
    try:
        try:
            cred = conn.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, 8)
            pid, uid, gid = struct.unpack("iii", cred)
        except OSError as e:
            log.warning("rejected connection: %s", e)
            return
        if uid != allow_uid:
            log.warning("rejected connection uid=%d (want %d)", uid, allow_uid)
            return
        conn.settimeout(60)
        buf = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    req = json.loads(line)
                except (ValueError, TypeError):
                    resp = {"ok": False, "error": "bad request"}
                else:
                    resp = dispatch(req, log)
                conn.sendall((json.dumps(resp) + "\n").encode())
    except (OSError, TimeoutError):
        pass
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="OSControl host executor")
    ap.add_argument("--socket", default="/run/osagent/executor.sock")
    args = ap.parse_args()
    log = common.setup_logging()
    allow_uid = os.getuid()
    sockdir = os.path.dirname(args.socket)
    if sockdir:
        os.makedirs(sockdir, exist_ok=True)
        try:
            os.chmod(sockdir, 0o750)
        except OSError:
            pass
    if os.path.exists(args.socket):
        os.unlink(args.socket)
    ln = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    ln.bind(args.socket)
    os.chmod(args.socket, 0o660)
    ln.listen(16)
    log.info("executor listening socket=%s allow_uid=%d", args.socket, allow_uid)
    while True:
        conn, _ = ln.accept()
        threading.Thread(target=handle, args=(conn, allow_uid, log), daemon=True).start()


if __name__ == "__main__":
    main()
