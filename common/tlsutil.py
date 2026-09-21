"""mTLS SSL context builders for TinyOSControll.

A single shared self-signed certificate (cert.crt / cert.key) is used for both
sides: main presents it as the server cert, each agent presents it as the
client cert, and both trust it as the CA. This gives mutual TLS (both sides
authenticate) with a single file to distribute.
"""

from __future__ import annotations

import os
import ssl


class TlsConfigError(RuntimeError):
    """Raised when certificate files are missing or unreadable."""


def _require(path: str, what: str) -> str:
    if not path or not os.path.isfile(path):
        raise TlsConfigError(f"missing {what}: {path!r}")
    return path


def load_server_context(ca: str, cert: str, key: str,
                        min_version: ssl.TLSVersion = ssl.TLSVersion.TLSv1_2) -> ssl.SSLContext:
    """SSL context for main (server). Requires a client certificate (mTLS)."""
    ca = _require(ca, "CA cert")
    cert = _require(cert, "server cert")
    key = _require(key, "server key")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = min_version
    ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.load_verify_locations(cafile=ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def load_client_context(ca: str, cert: str, key: str,
                        min_version: ssl.TLSVersion = ssl.TLSVersion.TLSv1_2) -> ssl.SSLContext:
    """SSL context for agent (client). Presents the client cert (mTLS)."""
    ca = _require(ca, "CA cert")
    cert = _require(cert, "client cert")
    key = _require(key, "client key")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = min_version
    ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = True
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.load_verify_locations(cafile=ca)
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def load_web_context(cert: str, key: str,
                     min_version: ssl.TLSVersion = ssl.TLSVersion.TLSv1_2) -> ssl.SSLContext:
    """SSL context for main's public web UI (HTTPS, no client cert required).

    Browsers cannot easily present a client cert, so the web UI relies on the
    static API token for authorization instead of mTLS.
    """
    cert = _require(cert, "web cert")
    key = _require(key, "web key")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = min_version
    ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.verify_mode = ssl.CERT_NONE
    return ctx
