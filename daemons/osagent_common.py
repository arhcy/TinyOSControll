"""Shared helpers for OSControl daemons: config, logging, TLS.

Standard library only — no third-party packages on the host.
"""
import json
import logging
import re
import ssl
import sys

VERSION = "0.2.0"

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


class ConfigError(Exception):
    pass


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        msg = json.dumps(record.getMessage())
        ts = self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z")
        return '{"ts":"%s","level":"%s","msg":%s}' % (ts, record.levelname, msg)


def setup_logging():
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format=_JsonFormatter(),
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    return logging.getLogger("osagent")


def parse_mac(s):
    s = (s or "").strip()
    if not MAC_RE.match(s):
        raise ConfigError("invalid MAC address %r" % (s,))
    return bytes(int(x, 16) for x in s.split(":"))


def _valid_ip(s):
    import ipaddress
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def validate_controller(cfg):
    errs = []
    listen = cfg.get("listen") or {}
    if not listen.get("web"):
        errs.append("listen.web is required")
    if not listen.get("management"):
        errs.append("listen.management is required")
    if len(cfg.get("api_token") or "") < 16:
        errs.append("api_token must be at least 16 characters")
    wol = cfg.get("wol") or {}
    try:
        parse_mac(wol.get("mac"))
    except ConfigError as e:
        errs.append(str(e))
    if wol.get("ip") and not _valid_ip(wol["ip"]):
        errs.append("wol.ip %r is not a valid IP" % wol["ip"])
    port = wol.get("port") or 0
    if not (0 < port <= 65535):
        wol["port"] = 9
    hm = (cfg.get("telemetry") or {}).get("history_minutes") or 0
    if hm <= 0:
        cfg.setdefault("telemetry", {})["history_minutes"] = 60
    tls = cfg.get("tls") or {}
    for name in ("ca", "cert", "key"):
        if not tls.get(name):
            errs.append("tls.%s is required" % name)
    if errs:
        raise ConfigError("; ".join(errs))


def validate_agent(cfg):
    errs = []
    url = (cfg.get("controller") or {}).get("url") or ""
    if not url.startswith("wss://") or not url[6:].split("/")[0]:
        errs.append("controller.url must be a wss:// URL")
    if not (cfg.get("executor") or {}).get("socket"):
        errs.append("executor.socket is required")
    docker = cfg.get("docker") or {}
    if not docker.get("endpoint"):
        errs.append("docker.endpoint is required")
    names = docker.get("containers") or []
    if not names:
        errs.append("docker.containers whitelist must not be empty")
    for n in names:
        if not CONTAINER_NAME_RE.match(n or ""):
            errs.append("docker.containers: invalid name %r" % (n,))
    interval = float((cfg.get("telemetry") or {}).get("interval") or 1.0)
    cfg.setdefault("telemetry", {})["interval"] = max(interval, 1.0)
    tls = cfg.get("tls") or {}
    for name in ("ca", "cert", "key"):
        if not tls.get(name):
            errs.append("tls.%s is required" % name)
    if errs:
        raise ConfigError("; ".join(errs))


def load_config(path, kind):
    try:
        with open(path) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise ConfigError("read config: no such file %s" % path)
    except json.JSONDecodeError as e:
        raise ConfigError("parse config: %s" % e)
    if kind == "controller":
        validate_controller(cfg)
    else:
        validate_agent(cfg)
    return cfg


def tls_server_context(cert, key, ca=None, require_client=False):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    if require_client:
        if not ca:
            raise ConfigError("tls.ca is required for mTLS")
        ctx.load_verify_locations(cafile=ca)
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def tls_client_context(cert, key, ca):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.load_verify_locations(cafile=ca)
    return ctx
