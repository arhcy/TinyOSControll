import pytest

from common import protocol as P


def test_roundtrip_each_type():
    samples = [
        P.make_hello("alpha", "tok"),
        P.make_hello_ok(),
        P.make_hello_err("unknown agent"),
        P.make_request(P.ACTION_HEALTH),
        P.make_request(P.ACTION_CONTAINERS_ACTION,
                       {"container": "nginx", "action": "start"}),
        P.make_response("id1", True, {"ok": 1}),
        P.make_response("id1", False, error="boom"),
        P.make_telemetry("alpha", "2026-01-01T00:00:00Z", {"ram": {}}),
        P.make_ping(),
        P.make_pong(),
        P.make_bye(),
    ]
    for msg in samples:
        line = P.encode(msg)
        assert isinstance(line, str)
        back = P.decode(line)
        assert back == msg


def test_decode_rejects_bad_json():
    with pytest.raises(P.ProtocolError):
        P.decode("{not json")


def test_decode_rejects_unknown_type():
    with pytest.raises(P.ProtocolError):
        P.decode('{"type":"explode"}')


def test_decode_rejects_non_object():
    with pytest.raises(P.ProtocolError):
        P.decode("[1,2,3]")


def test_encode_requires_type():
    with pytest.raises(P.ProtocolError):
        P.encode({"nope": 1})


def test_make_request_rejects_unknown_action():
    with pytest.raises(P.ProtocolError):
        P.make_request("rm -rf /")


def test_request_has_unique_ids():
    a = P.make_request(P.ACTION_HEALTH)
    b = P.make_request(P.ACTION_HEALTH)
    assert a["id"] != b["id"]
