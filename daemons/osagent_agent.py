#!/usr/bin/env python3
"""OSControl agent (Target host, systemd, user osagent).

Connects OUTBOUND to the controller over mTLS WebSocket (no inbound ports
on the target), executes management actions, collects telemetry. Talks to
the host executor (unix socket) and the docker proxy (unix socket).
Standard library only.
"""
import argparse
import http.client
import json
import re
import socket
import threading
import time
import urllib.parse

import osagent_common as common
import wslib


class ExecutorClient:
    def __init__(self, socket_path):
        self.socket_path = socket_path

    def call(self, cmd, timeout=20.0):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(self.socket_path)
            s.sendall((json.dumps({"cmd": cmd}) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(4096)
                if not chunk:
                    raise RuntimeError("executor closed connection")
                buf += chunk
            resp = json.loads(buf.split(b"\n", 1)[0])
            if not resp.get("ok"):
                raise RuntimeError("executor: %s" % resp.get("error", ""))
            return resp.get("data")
        finally:
            s.close()

    def sysinfo(self):
        return self.call("sysinfo")

    def amdsmi(self):
        return self.call("amdsmi")

    def poweroff(self):
        self.call("poweroff", timeout=25.0)


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout=10):
        super().__init__("docker", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if self.timeout is not None:
            s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


class DockerClient:
    """Minimal Docker Engine API client (v1.47) via the local proxy socket."""

    def __init__(self, endpoint):
        if not endpoint.startswith("unix://"):
            raise common.ConfigError("unsupported docker endpoint %r (want unix://)" % endpoint)
        self.path = endpoint[len("unix://"):]

    def list(self):
        c = UnixHTTPConnection(self.path)
        try:
            c.request("GET", "/v1.47/containers/json")
            r = c.getresponse()
            body = r.read()
            if r.status not in (200, 204, 304):
                raise RuntimeError("docker api: status %d" % r.status)
            return json.loads(body) if body else []
        finally:
            c.close()

    def action(self, name, act):
        c = UnixHTTPConnection(self.path)
        try:
            c.request("POST", "/v1.47/containers/%s/%s" % (name, act))
            r = c.getresponse()
            r.read()
            if r.status in (200, 204, 304):
                return
            if r.status == 409:
                raise RuntimeError("container already in desired state")
            if r.status == 404:
                raise RuntimeError("container not found")
            raise RuntimeError("docker api: status %d" % r.status)
        finally:
            c.close()


RE_GPU = {
    "temp_c": re.compile(r"GPU temperature \(C\)\s*:\s*([\d.]+)", re.M),
    "use_pct": re.compile(r"GPU use \(\%\)\s*:\s*([\d.]+)", re.M),
    "mem_use_pct": re.compile(r"GPU memory use \(\%\)\s*:\s*([\d.]+)", re.M),
    "core_clock_mhz": re.compile(r"GPU core clock \(MHz\)\s*:\s*([\d.]+)", re.M),
    "mem_clock_mhz": re.compile(r"GPU memory core clock \(MHz\)\s*:\s*([\d.]+)", re.M),
}


def parse_amdsmi(raw):
    """Extract GPU metrics from amd-smi monitor output (first match)."""
    g = {"raw": (raw or "").strip()}
    for key, rx in RE_GPU.items():
        m = rx.search(raw or "")
        if m:
            v = float(m.group(1))
            g[key] = int(v) if key.endswith("mhz") else v
    return g


class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.log = common.setup_logging()
        self.exec = ExecutorClient(cfg["executor"]["socket"])
        self.docker = DockerClient(cfg["docker"]["endpoint"])
        self.allowed = set(cfg["docker"]["containers"])
        u = urllib.parse.urlparse(cfg["controller"]["url"])
        self.host = u.hostname
        self.port = u.port or 443
        self.path = u.path or "/ws"
        tls = cfg["tls"]
        self.tls_ctx = common.tls_client_context(tls["cert"], tls["key"], tls["ca"])
        self.interval = float(cfg["telemetry"]["interval"])
        self.write_lock = threading.Lock()

    def run(self):
        backoff = 1.0
        while True:
            try:
                raw = socket.create_connection((self.host, self.port), timeout=10)
                tls = self.tls_ctx.wrap_socket(raw, server_hostname=self.host)
                leftover = wslib.client_handshake(tls, self.host, self.path)
                ws = wslib.WebSocket(tls, leftover, is_server=False)
            except Exception as e:
                self.log.warning("controller dial failed: %s", e)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            self.log.info("connected to controller")
            backoff = 1.0
            self.serve(ws)
            self.log.info("disconnected from controller")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def serve(self, ws):
        stop = threading.Event()
        t = threading.Thread(target=self.telemetry_loop, args=(ws, stop), daemon=True)
        t.start()
        try:
            while True:
                try:
                    msg = json.loads(ws.recv())
                except wslib.WSError:
                    break
                except ValueError:
                    continue
                if msg.get("type") != "request":
                    continue
                threading.Thread(target=self.handle_request, args=(ws, msg), daemon=True).start()
        finally:
            stop.set()
            t.join(timeout=5)

    def send(self, ws, obj):
        with self.write_lock:
            ws.send(json.dumps(obj))

    def handle_request(self, ws, req):
        resp = {"type": "response", "id": req.get("id")}
        payload = None
        try:
            action = req.get("action")
            if action == "health":
                si = self.exec.sysinfo()
                payload = {"version": common.VERSION,
                           "hostname": si.get("hostname"),
                           "uptime_sec": si.get("uptime_sec", 0)}
            elif action == "shutdown":
                self.exec.poweroff()
            elif action == "containers.list":
                payload = {"containers": self.list_containers()}
            elif action == "containers.action":
                p = req.get("payload") or {}
                self.do_container_action(p.get("name"), p.get("action"))
            else:
                raise RuntimeError("unknown action")
            resp["ok"] = True
            if payload is not None:
                resp["payload"] = payload
        except Exception as e:
            resp["ok"] = False
            resp["error"] = str(e)
        try:
            self.send(ws, resp)
        except Exception as e:
            self.log.warning("write response failed: %s", e)

    def list_containers(self):
        out = []
        for c in self.docker.list():
            for name in c.get("Names") or []:
                name = name.lstrip("/")
                if name in self.allowed:
                    out.append({"name": name, "state": c.get("State"), "status": c.get("Status")})
                    break
        return out

    def do_container_action(self, name, action):
        if not name or not common.CONTAINER_NAME_RE.match(name):
            raise RuntimeError("invalid container name")
        if name not in self.allowed:
            raise RuntimeError("container %r is not in the whitelist" % name)
        if action not in ("start", "stop", "restart"):
            raise RuntimeError("invalid action %r" % action)
        self.docker.action(name, action)

    def telemetry_loop(self, ws, stop):
        while not stop.is_set():
            if stop.wait(self.interval):
                return
            try:
                self.send(ws, {"type": "telemetry", "payload": self.collect()})
            except Exception:
                return

    def collect(self):
        payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        results = {}

        def get_sysinfo():
            try:
                results["si"] = self.exec.sysinfo()
            except Exception as e:
                results["si_err"] = e

        def get_gpu():
            try:
                results["gpu"] = (self.exec.amdsmi() or {}).get("raw", "")
            except Exception as e:
                results["gpu_err"] = e

        threads = [threading.Thread(target=get_sysinfo), threading.Thread(target=get_gpu)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        si = results.get("si")
        if si:
            payload["hostname"] = si.get("hostname")
            payload["uptime_sec"] = si.get("uptime_sec", 0)
            payload["cpu"] = si.get("thermals", [])
            if "ram" in si:
                payload["ram"] = si["ram"]
            if "load" in si:
                payload["load"] = si["load"]
        if "gpu" in results and results["gpu"]:
            payload["gpu"] = parse_amdsmi(results["gpu"])
        return payload


def main():
    ap = argparse.ArgumentParser(description="OSControl agent")
    ap.add_argument("--config", default="/etc/osagent/agent.json")
    args = ap.parse_args()
    cfg = common.load_config(args.config, kind="agent")
    Agent(cfg).run()


if __name__ == "__main__":
    main()
