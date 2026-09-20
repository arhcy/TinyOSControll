#!/usr/bin/env python3
"""OSControl controller (Control host, systemd, user osagent).

Web panel (HTTPS, static API token, SSE live updates) + mTLS WebSocket
management channel for the agent + Wake-on-LAN + telemetry store + audit
log. Standard library only.
"""
import argparse
import hmac
import json
import os
import queue
import socket
import socketserver
import ssl
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import osagent_common as common
import wslib

WEB_FILES = ("index.html", "app.js", "style.css")
CONTENT_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}


class RateLimiter:
    """Per-key token bucket."""

    def __init__(self, capacity=10, refill=6.0):
        self.capacity = capacity
        self.refill = refill
        self.mu = threading.Lock()
        self.buckets = {}

    def allow(self, key):
        now = time.monotonic()
        with self.mu:
            b = self.buckets.get(key)
            if b is None:
                self.buckets[key] = [self.capacity, now]
                return True
            tokens, last = b
            tokens += (now - last) / self.refill
            if tokens > self.capacity:
                tokens = self.capacity
            if tokens < 1:
                self.buckets[key] = [tokens, now]
                return False
            self.buckets[key] = [tokens - 1, now]
            return True


class Hub:
    """Fans events out to SSE subscribers (drops for slow ones)."""

    def __init__(self):
        self.mu = threading.Lock()
        self.subs = []

    def subscribe(self):
        ch = queue.Queue(maxsize=64)
        with self.mu:
            self.subs.append(ch)

        def cancel():
            with self.mu:
                if ch in self.subs:
                    self.subs.remove(ch)
        return ch, cancel

    def publish(self, event, data):
        with self.mu:
            subs = list(self.subs)
        for ch in subs:
            try:
                ch.put_nowait((event, data))
            except queue.Full:
                pass


class TelemetryStore:
    def __init__(self, maxlen=3600):
        self.mu = threading.Lock()
        self.frames = deque(maxlen=max(1, maxlen))
        self.last = None

    def add(self, f):
        with self.mu:
            self.frames.append(f)
            self.last = f

    def latest(self):
        with self.mu:
            return self.last


class AgentClient:
    """Manages the single mTLS WebSocket connection from the agent."""

    def __init__(self, log, hub, store):
        self.log = log
        self.hub = hub
        self.store = store
        self.mu = threading.Lock()
        self.write_lock = threading.Lock()
        self.conn = None
        self.online = False
        self.pending = {}

    def accept(self, ws):
        with self.mu:
            old = self.conn
            self.conn = ws
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self.online = True
        self.log.info("agent connected")
        t = threading.Thread(target=self.reader, args=(ws,), daemon=True)
        t.start()
        t.join()
        with self.mu:
            if self.conn is ws:
                self.conn = None
        self.online = False
        self.log.info("agent disconnected")

    def reader(self, ws):
        while True:
            try:
                msg = json.loads(ws.recv())
            except wslib.WSError:
                return
            except ValueError:
                continue
            self.handle_message(msg)

    def handle_message(self, msg):
        t = msg.get("type")
        if t == "response":
            with self.mu:
                p = self.pending.pop(msg.get("id"), None)
            if p:
                p["ch"].put(msg)
        elif t == "telemetry":
            payload = msg.get("payload") or {}
            self.store.add(payload)
            self.hub.publish("telemetry", json.dumps(payload))

    def request(self, action, payload=None, timeout=15.0):
        with self.mu:
            conn = self.conn
        if conn is None:
            raise RuntimeError("agent offline")
        rid = uuid.uuid4().hex
        ch = queue.Queue(maxsize=1)
        with self.mu:
            self.pending[rid] = {"ch": ch}
        try:
            msg = {"type": "request", "id": rid, "action": action}
            if payload is not None:
                msg["payload"] = payload
            with self.write_lock:
                conn.send(json.dumps(msg))
            m = ch.get(timeout=timeout)
            if m.get("ok") is False:
                raise RuntimeError(m.get("error") or "agent error")
            return m.get("payload")
        finally:
            with self.mu:
                self.pending.pop(rid, None)


class MgmtHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            path, leftover = wslib.server_handshake(self.request)
        except Exception:
            return
        ws = wslib.WebSocket(self.request, leftover, is_server=True)
        self.server.agent_client.accept(ws)


class MgmtServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class WebHandler(BaseHTTPRequestHandler):
    server_version = "OSAgent"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet; audit log is explicit
        pass

    def _auth_ok(self):
        key = self.headers.get("X-API-Key")
        if not key:
            key = parse_qs(urlsplit(self.path).query).get("key", [""])[0]
        return hmac.compare_digest(key.encode(), self.server.api_token.encode())

    def _err(self, code, msg):
        body = msg.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == "/api/status":
                if not self._auth_ok():
                    return self._err(401, "unauthorized")
                return self._json(self.server.status_snapshot())
            if path == "/api/events":
                if not self._auth_ok():
                    return self._err(401, "unauthorized")
                return self._sse()
            name = path.lstrip("/") or "index.html"
            data = self.server.web_files.get(name)
            if data is None:
                return self._err(404, "not found")
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES[name])
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    def do_POST(self):
        if urlsplit(self.path).path != "/api/actions":
            return self._err(405, "method not allowed")
        try:
            if not self._auth_ok():
                return self._err(401, "unauthorized")
            ip = self.client_address[0]
            if not self.server.limiter.allow(ip):
                return self._err(429, "rate limited")
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(length, 1024))
            req = json.loads(body)
            start = time.monotonic()
            err = None
            if req.get("action") == "wol":
                self.server.send_wol()
            elif req.get("action") == "shutdown":
                self.server.agent_client.request("shutdown", None)
            elif req.get("action") == "container":
                name = req.get("name") or ""
                op = req.get("op") or ""
                if not common.CONTAINER_NAME_RE.match(name):
                    return self._err(400, "invalid container name")
                if op not in ("start", "stop", "restart"):
                    return self._err(400, "invalid op")
                self.server.agent_client.request(
                    "containers.action", {"name": name, "action": op})
            else:
                return self._err(400, "unknown action")
            self.server.log.info(
                "action action=%s name=%s op=%s ip=%s ok=%s dur_ms=%d",
                req.get("action"), req.get("name", ""), req.get("op", ""),
                ip, err is None, int((time.monotonic() - start) * 1000))
            return self._json({"ok": True})
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass
        except ValueError:
            return self._err(400, "bad request")
        except Exception as e:
            self.server.log.info("action failed: %s", e)
            try:
                return self._err(502, str(e))
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                pass

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        ch, cancel = self.server.hub.subscribe()
        try:
            self._sse_send("status", json.dumps(self.server.status_snapshot()))
            while True:
                try:
                    event, data = ch.get(timeout=30)
                    self._sse_send(event, data)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError, OSError):
            pass
        finally:
            cancel()

    def _sse_send(self, event, data):
        self.wfile.write(("event: %s\ndata: %s\n\n" % (event, data)).encode())
        self.wfile.flush()


def parse_listen(s):
    host, _, port = s.rpartition(":")
    return (host or "", int(port))


class Server:
    def __init__(self, cfg):
        self.cfg = cfg
        self.log = common.setup_logging()
        self.hub = Hub()
        self.store = TelemetryStore(cfg["telemetry"]["history_minutes"] * 60)
        self.limiter = RateLimiter(10, 6.0)
        self.agent_client = AgentClient(self.log, self.hub, self.store)
        self.wol_mac = common.parse_mac(cfg["wol"]["mac"])
        self.wol_ip = cfg["wol"].get("ip") or ""
        self.wol_port = int(cfg["wol"].get("port") or 9)
        self.api_token = cfg["api_token"]
        self.containers = []
        webdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
        self.web_files = {}
        for name in WEB_FILES:
            with open(os.path.join(webdir, name), "rb") as f:
                self.web_files[name] = f.read()
        tls = cfg["tls"]
        self.ws_tls = common.tls_server_context(tls["cert"], tls["key"],
                                                ca=tls["ca"], require_client=True)
        self.web_tls = common.tls_server_context(tls["cert"], tls["key"])

    def status_snapshot(self):
        return {
            "agent_online": self.agent_client.online,
            "wol_mac": self.cfg["wol"]["mac"],
            "containers": self.containers,
            "telemetry": self.store.latest(),
        }

    def send_wol(self):
        pkt = bytes([0xFF] * 6) + self.wol_mac * 16
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(5)
            s.sendto(pkt, ("255.255.255.255", self.wol_port))
            if self.wol_ip:
                s.sendto(pkt, (self.wol_ip, self.wol_port))
        finally:
            s.close()

    def poll_containers(self):
        while True:
            time.sleep(5)
            if not self.agent_client.online:
                continue
            try:
                p = self.agent_client.request("containers.list", None, timeout=10)
            except Exception:
                continue
            self.containers = (p or {}).get("containers", [])
            self.hub.publish("containers", json.dumps({"containers": self.containers}))

    def run(self):
        httpd = ThreadingHTTPServer(parse_listen(self.cfg["listen"]["web"]), WebHandler)
        httpd.daemon_threads = True
        httpd.api_token = self.api_token
        httpd.hub = self.hub
        httpd.limiter = self.limiter
        httpd.agent_client = self.agent_client
        httpd.web_files = self.web_files
        httpd.status_snapshot = self.status_snapshot
        httpd.send_wol = self.send_wol
        httpd.log = self.log
        httpd.socket = self.web_tls.wrap_socket(httpd.socket, server_side=True)
        mgmt = MgmtServer(parse_listen(self.cfg["listen"]["management"]), MgmtHandler)
        mgmt.agent_client = self.agent_client
        mgmt.socket = self.ws_tls.wrap_socket(mgmt.socket, server_side=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        threading.Thread(target=mgmt.serve_forever, daemon=True).start()
        threading.Thread(target=self.poll_containers, daemon=True).start()
        self.log.info("web listening on %s", self.cfg["listen"]["web"])
        self.log.info("management listening on %s (mTLS)", self.cfg["listen"]["management"])
        threading.Event().wait()


def main():
    ap = argparse.ArgumentParser(description="OSControl controller")
    ap.add_argument("--config", default="/etc/osagent/controller.json")
    args = ap.parse_args()
    cfg = common.load_config(args.config, kind="controller")
    Server(cfg).run()


if __name__ == "__main__":
    main()
