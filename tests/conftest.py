"""Shared pytest fixtures.

Generates a self-signed certificate (via openssl) so the mTLS code paths can be
exercised locally without real servers. Skips cleanly if openssl is unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest


def _find_openssl() -> str | None:
    p = shutil.which("openssl")
    if p:
        return p
    candidates = [
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files (x86)\Git\usr\bin\openssl.exe",
        "/usr/bin/openssl",
        "/usr/local/bin/openssl",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _gen_cert(openssl: str, out_dir: str, host: str) -> None:
    import ipaddress

    alt_lines = ["DNS.1 = localhost", "IP.1 = 127.0.0.1"]
    idx = 2
    try:
        ipaddress.ip_address(host)
        alt_lines.append(f"IP.{idx} = {host}")
    except ValueError:
        alt_lines.append(f"DNS.{idx} = {host}")

    cfg = (
        "[req]\n"
        "distinguished_name = dn\n"
        "x509_extensions = v3\n"
        "prompt = no\n"
        "[dn]\n"
        "CN = TinyOSControll\n"
        "[v3]\n"
        "basicConstraints = critical, CA:TRUE\n"
        "keyUsage = critical, digitalSignature, keyEncipherment, keyCertSign\n"
        "extendedKeyUsage = serverAuth, clientAuth\n"
        "subjectAltName = @alt\n"
        "[alt]\n" + "\n".join(alt_lines) + "\n"
    )
    cfg_path = os.path.join(out_dir, "openssl.cnf")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write(cfg)
    subprocess.run(
        [
            openssl, "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", "cert.key", "-out", "cert.crt",
            "-days", "825", "-nodes", "-config", cfg_path,
        ],
        cwd=out_dir,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def openssl() -> str:
    p = _find_openssl()
    if not p:
        pytest.skip("openssl not available")
    return p


@pytest.fixture(scope="session")
def cert_dir(openssl, tmp_path_factory) -> str:
    d = tmp_path_factory.mktemp("certs")
    _gen_cert(openssl, str(d), "localhost")
    return str(d)
