"""Minimal RFC 6455 WebSocket (text frames) over an already-established socket.

Standard library only. Used by the controller (server side) and the agent
(client side). Supports: text frames, ping/pong, close. No extensions and
no fragmentation (messages are small JSON documents).
"""
import base64
import hashlib
import os
import struct

_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WSError(Exception):
    pass


def _read_headers(sock):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise WSError("connection closed during handshake")
        data += chunk
        if len(data) > 65536:
            raise WSError("handshake too large")
    head, rest = data.split(b"\r\n\r\n", 1)
    lines = head.decode("latin-1").split("\r\n")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return lines[0], headers, rest


def server_handshake(sock):
    """Server side of the WS upgrade. Returns (path, leftover_bytes)."""
    reqline, headers, rest = _read_headers(sock)
    parts = reqline.split(" ")
    if len(parts) != 3 or parts[0] != "GET":
        raise WSError("not a websocket upgrade request")
    if headers.get("upgrade", "").lower() != "websocket":
        raise WSError("missing Upgrade: websocket")
    key = headers.get("sec-websocket-key", "")
    if not key:
        raise WSError("missing Sec-WebSocket-Key")
    accept = base64.b64encode(hashlib.sha1((key + _MAGIC).encode()).digest()).decode()
    resp = ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: " + accept + "\r\n\r\n")
    sock.sendall(resp.encode())
    return parts[1], rest


def client_handshake(sock, host, path):
    """Client side of the WS upgrade. Returns leftover bytes."""
    if not path.startswith("/"):
        path = "/" + path
    key = base64.b64encode(os.urandom(16)).decode()
    req = ("GET " + path + " HTTP/1.1\r\n"
           "Host: " + host + "\r\n"
           "Upgrade: websocket\r\n"
           "Connection: Upgrade\r\n"
           "Sec-WebSocket-Key: " + key + "\r\n"
           "Sec-WebSocket-Version: 13\r\n\r\n")
    sock.sendall(req.encode())
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise WSError("connection closed during handshake")
        data += chunk
        if len(data) > 65536:
            raise WSError("handshake response too large")
    status_line = data.split(b"\r\n", 1)[0].decode("latin-1")
    if " 101 " not in status_line + " ":
        raise WSError("handshake failed: " + status_line)
    _, rest = data.split(b"\r\n\r\n", 1)
    return rest


class WebSocket:
    """A small blocking WebSocket. is_server decides frame masking."""

    def __init__(self, sock, leftover=b"", is_server=True):
        self.sock = sock
        self.is_server = is_server
        self._buf = leftover
        self.closed = False

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WSError("connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_frame(self):
        b0, b1 = self._read(2)
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]
        mask = self._read(4) if masked else b""
        payload = self._read(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def _send_frame(self, opcode, payload):
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([n])
        elif n < 65536:
            header += bytes([126]) + struct.pack(">H", n)
        else:
            header += bytes([127]) + struct.pack(">Q", n)
        if not self.is_server:
            mask = os.urandom(4)
            header += mask
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + payload)

    def send(self, text):
        if self.closed:
            raise WSError("socket closed")
        self._send_frame(0x1, text.encode("utf-8"))

    def recv(self):
        """Return the next text message. Answers pings, raises WSError on close."""
        while True:
            opcode, payload = self._read_frame()
            if opcode == 0x8:  # close
                self.close()
                raise WSError("closed by peer")
            if opcode == 0x9:  # ping -> pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode in (0x1, 0x2):
                return payload.decode("utf-8")
            raise WSError("unsupported opcode %d" % opcode)

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self._send_frame(0x8, b"")
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
