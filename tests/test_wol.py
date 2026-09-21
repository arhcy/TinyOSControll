import pytest

from common import wol


def test_parse_mac_colons():
    assert wol.parse_mac("AA:BB:CC:DD:EE:FF") == bytes.fromhex("aabbccddeeff")


def test_parse_mac_dashes_and_dots():
    assert wol.parse_mac("aa-bb-cc-dd-ee-ff") == bytes.fromhex("aabbccddeeff")
    assert wol.parse_mac("AA.BB.CC.DD.EE.FF") == bytes.fromhex("aabbccddeeff")


def test_parse_mac_no_separators():
    assert wol.parse_mac("aabbccddeeff") == bytes.fromhex("aabbccddeeff")


@pytest.mark.parametrize("bad", ["", "AA:BB:CC:DD:EE", "GG:BB:CC:DD:EE:FF", "aabbccddeeff00"])
def test_parse_mac_invalid(bad):
    with pytest.raises(wol.WolError):
        wol.parse_mac(bad)


def test_magic_packet_structure():
    pkt = wol.magic_packet("AA:BB:CC:DD:EE:FF")
    assert len(pkt) == 102
    assert pkt[:6] == b"\xff" * 6
    mac = bytes.fromhex("aabbccddeeff")
    assert pkt[6:] == mac * 16


def test_magic_packet_invalid_mac():
    with pytest.raises(wol.WolError):
        wol.magic_packet("nope")
