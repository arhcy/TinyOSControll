import os

import pytest

from common import tlsutil


def test_load_server_context(cert_dir):
    ctx = tlsutil.load_server_context(
        ca=os.path.join(cert_dir, "cert.crt"),
        cert=os.path.join(cert_dir, "cert.crt"),
        key=os.path.join(cert_dir, "cert.key"),
    )
    assert ctx.verify_mode.name == "CERT_REQUIRED"


def test_load_client_context(cert_dir):
    ctx = tlsutil.load_client_context(
        ca=os.path.join(cert_dir, "cert.crt"),
        cert=os.path.join(cert_dir, "cert.crt"),
        key=os.path.join(cert_dir, "cert.key"),
    )
    assert ctx.verify_mode.name == "CERT_REQUIRED"
    assert ctx.check_hostname is True


def test_missing_file_raises(cert_dir):
    with pytest.raises(tlsutil.TlsConfigError):
        tlsutil.load_server_context(
            ca=os.path.join(cert_dir, "nope.crt"),
            cert=os.path.join(cert_dir, "cert.crt"),
            key=os.path.join(cert_dir, "cert.key"),
        )
