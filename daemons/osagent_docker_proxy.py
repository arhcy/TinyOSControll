#!/usr/bin/env python3
"""OSControl docker socket proxy (Target host, systemd, root).

Forwards ONLY an allowlisted subset of the Docker Engine API from a local
unix socket to the real docker socket. The agent never touches the real
socket. Same allowlist semantics as docker-socket-proxy containers=1:
  GET  /containers/json
  POST /containers/<name>/start|stop|restart
Standard library only.
"""
import argparse
import http.client
import os
import pwd
import re
import socket
import socketserver

import osagent_common as common

NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
VERSION_RE = re.compile(r"^/v\d+\.\d+")
ACTION_RE = re.compile(r"^/containers/([^/]+)/(start|stop|restart)$")


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


def is_allowed(method, path):
    p = VERSION_RE.sub("", path)
    if method == "GET" and p == "/containers/json":
        return True
    m = ACTION_RE.match(p)
    if method == "POST" and m and NAME_RE.match(m.group(1)):
        return True
    return False


def osagent_gid():
    try:
        return pwd.getpwnam("osagent").pw_gid
    except KeyError:
        return 0


class ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        conn = self.request
        try:
            conn.settimeout(30)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                data += chunk
                if len(data) > (1 << 20):
                    return self.reply(413, b"request too large")
            head, rest = data.split(b"\r\n\r\n", 1)
            lines = head.decode("latin-1").split("\r\n")
            parts = lines[0].split(" ")
            if len(parts) != 3:
                return self.reply(400, b"bad request")
            method, path = parts[0], parts[1]
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            if not is_allowed(method, path):
                self.server.log.info("denied %s %s", method, path)
                return self.reply(403, b"not allowed")
            length = int(headers.get("content-length") or 0)
            body = rest
            while len(body) < length:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                body += chunk
            body = body[:length] or None
            c = UnixHTTPConnection(self.server.backend)
            fwd = {k: v for k, v in headers.items()
                   if k not in ("host", "content-length", "connection")}
            c.request(method, path, body=body, headers=fwd)
            r = c.getresponse()
            rbody = r.read()
            self.reply(r.status, rbody)
        except Exception as e:
            self.server.log.warning("proxy error: %s", e)
            try:
                self.reply(502, str(e).encode())
            except OSError:
                pass
        finally:
            conn.close()

    def reply(self, status, body):
        reasons = {200: "OK", 204: "No Content", 304: "Not Modified", 400: "Bad Request",
                   403: "Forbidden", 404: "Not Found", 409: "Conflict",
                   413: "Payload Too Large", 502: "Bad Gateway"}
        head = ("HTTP/1.1 %d %s\r\n"
                "Content-Type: application/json\r\n"
                "Content-Length: %d\r\n"
                "Connection: close\r\n\r\n") % (status, reasons.get(status, "OK"), len(body))
        self.request.sendall(head.encode() + body)


class UnixServer(socketserver.ThreadingTCPServer):
    address_family = socket.AF_UNIX
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser(description="OSControl docker socket proxy")
    ap.add_argument("--listen", default="/run/osagent/docker.sock")
    ap.add_argument("--backend", default="/var/run/docker.sock")
    args = ap.parse_args()
    log = common.setup_logging()
    sockdir = os.path.dirname(args.listen)
    if sockdir:
        os.makedirs(sockdir, exist_ok=True)
        try:
            os.chown(sockdir, 0, osagent_gid())
            os.chmod(sockdir, 0o750)
        except (KeyError, PermissionError, OSError):
            pass
    if os.path.exists(args.listen):
        os.unlink(args.listen)
    srv = UnixServer(args.listen, ProxyHandler)
    os.chmod(args.listen, 0o660)
    try:
        os.chown(args.listen, 0, osagent_gid())
    except (KeyError, PermissionError, OSError):
        pass
    srv.backend = args.backend
    srv.log = log
    log.info("docker proxy listening %s -> %s (allowlist: containers only)", args.listen, args.backend)
    srv.serve_forever()


if __name__ == "__main__":
    main()
